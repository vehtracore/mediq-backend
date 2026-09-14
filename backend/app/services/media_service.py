import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import cloudinary
import cloudinary.uploader
import cloudinary.utils
from fastapi import HTTPException, UploadFile, status

from app.core.api_errors import ApiError

logger = logging.getLogger(__name__)

# Configure Cloudinary using environment variables.
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True,
)

_ALLOWED_FOLDERS = {
    "mdq_plus/general",
    "mdq_plus/doctors",
    "mdq_plus/doctor_licenses",
    "mdq_plus/indemnity_certs",
    "mdq_plus/profile_pics",
    "mediq_profile_pics",
}
_ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "application/pdf",
}
_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}
_MAX_UPLOAD_BYTES = 5 * 1024 * 1024
SENSITIVE_ACCESS_TTL_SECONDS = 5 * 60

_SENSITIVE_UPLOAD_POLICIES = {
    "doctor_license": (
        "mdq_plus/doctor_licenses",
        {"image/jpeg", "image/png", "image/webp", "application/pdf"},
    ),
    "doctor_indemnity": (
        "mdq_plus/indemnity_certs",
        {"image/jpeg", "image/png", "image/webp", "application/pdf"},
    ),
    "lab_image": (
        "mediq_lab_scans",
        {"image/jpeg", "image/png", "image/webp"},
    ),
}


@dataclass(frozen=True)
class SensitiveMediaAsset:
    public_id: str
    resource_type: str
    format: str
    delivery_type: str = "authenticated"


@dataclass(frozen=True)
class SensitiveMediaAccess:
    url: str
    expires_at: datetime
    expires_in: int


def detect_upload_media_type(content: bytes) -> str | None:
    """Identify supported media by file signature, never by client metadata."""
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def _file_extension(filename: str | None) -> str:
    if not filename or "." not in filename:
        return ""
    return "." + filename.rsplit(".", 1)[1].lower()


def _validate_client_filename(filename: str | None) -> None:
    if not filename:
        return
    if "\x00" in filename or "/" in filename or "\\" in filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file name.",
        )
    if filename in {".", ".."}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file name.",
        )


def validate_upload_folder(folder: str | None) -> str:
    clean_folder = (folder or "mdq_plus/general").strip().strip("/")
    if clean_folder not in _ALLOWED_FOLDERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid upload folder.",
        )
    return clean_folder


async def read_validated_upload(
    file: UploadFile,
    *,
    allowed_types: set[str] | None = None,
) -> bytes:
    _validate_client_filename(file.filename)
    content_type = (file.content_type or "").lower()
    extension = _file_extension(file.filename)
    if content_type not in _ALLOWED_CONTENT_TYPES and extension not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file type. Only JPG, PNG, WebP, and PDF files are allowed.",
        )

    content = await file.read(_MAX_UPLOAD_BYTES + 1)
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File exceeds the 5MB upload limit.",
        )
    detected_type = detect_upload_media_type(content)
    if detected_type is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File content is not a valid JPG, PNG, WebP, or PDF.",
        )
    if allowed_types is not None and detected_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This file type is not allowed for this upload.",
        )
    return content


async def upload_image(
    file: UploadFile,
    folder: str = "mdq_plus/general",
    *,
    allowed_types: set[str] | None = None,
) -> str:
    """Validate and upload an image/PDF to an approved Cloudinary folder."""
    clean_folder = validate_upload_folder(folder)
    content = await read_validated_upload(file, allowed_types=allowed_types)

    try:
        response = cloudinary.uploader.upload(
            content,
            folder=clean_folder,
            resource_type="auto",
        )
        secure_url = response.get("secure_url")
        if not secure_url:
            raise RuntimeError("Cloudinary response did not include secure_url")
        return secure_url

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "[MEDIA] Public upload failed failure_category=%s",
            type(exc).__name__,
        )
        raise HTTPException(status_code=502, detail="File upload failed") from exc


async def upload_sensitive_media(
    file: UploadFile,
    *,
    media_class: str,
) -> SensitiveMediaAsset:
    """Upload a server-classified asset with authenticated delivery.

    Callers select a logical media class, never a Cloudinary folder or public
    ID. Client filenames are validated but are not used for storage naming.
    """
    policy = _SENSITIVE_UPLOAD_POLICIES.get(media_class)
    if policy is None:
        raise ValueError("Unknown sensitive media class")
    folder, allowed_types = policy
    content = await read_validated_upload(file, allowed_types=allowed_types)

    try:
        response = cloudinary.uploader.upload(
            content,
            folder=folder,
            resource_type="auto",
            type="authenticated",
            use_filename=False,
            unique_filename=True,
            overwrite=False,
        )
        public_id = response.get("public_id")
        resource_type = response.get("resource_type")
        asset_format = response.get("format")
        if not public_id or resource_type not in {"image", "video", "raw"} or not asset_format:
            raise RuntimeError("Sensitive upload response was incomplete")
        return SensitiveMediaAsset(
            public_id=public_id,
            resource_type=resource_type,
            format=asset_format,
            delivery_type="authenticated",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "[SENSITIVE MEDIA] Upload failed media_class=%s failure_category=%s",
            media_class,
            type(exc).__name__,
        )
        raise ApiError(
            502,
            "media_upload_unavailable",
            "MDQ+ could not securely store this file. Please try again.",
        ) from exc


def generate_sensitive_access(
    asset: SensitiveMediaAsset,
    *,
    ttl_seconds: int = SENSITIVE_ACCESS_TTL_SECONDS,
) -> SensitiveMediaAccess:
    """Generate a short-lived Cloudinary download URL for one DB-owned asset."""
    if asset.delivery_type != "authenticated":
        raise ApiError(
            409,
            "media_migration_required",
            "This file is awaiting secure-media migration.",
        )
    if ttl_seconds < 30 or ttl_seconds > 15 * 60:
        raise ValueError("Sensitive media TTL must be between 30 and 900 seconds")

    expires_unix = int(time.time()) + ttl_seconds
    try:
        url = cloudinary.utils.private_download_url(
            asset.public_id,
            asset.format,
            resource_type=asset.resource_type,
            type=asset.delivery_type,
            expires_at=expires_unix,
            secure=True,
        )
    except Exception as exc:
        logger.error(
            "[SENSITIVE MEDIA] Access signing failed failure_category=%s",
            type(exc).__name__,
        )
        raise ApiError(
            503,
            "media_access_unavailable",
            "This file is temporarily unavailable. Please try again.",
        ) from exc

    return SensitiveMediaAccess(
        url=url,
        expires_at=datetime.fromtimestamp(expires_unix, tz=timezone.utc),
        expires_in=ttl_seconds,
    )


def delete_sensitive_media(asset: SensitiveMediaAsset) -> bool:
    """Best-effort deletion for uncommitted or explicitly disposable assets."""
    try:
        result = cloudinary.uploader.destroy(
            asset.public_id,
            resource_type=asset.resource_type,
            type=asset.delivery_type,
            invalidate=True,
        )
        return result.get("result") in {"ok", "not found"}
    except Exception as exc:
        logger.error(
            "[SENSITIVE MEDIA] Cleanup failed failure_category=%s",
            type(exc).__name__,
        )
        return False
