import logging
import os

import cloudinary
import cloudinary.uploader
from fastapi import HTTPException, UploadFile, status

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


def _file_extension(filename: str | None) -> str:
    if not filename or "." not in filename:
        return ""
    return "." + filename.rsplit(".", 1)[1].lower()


def validate_upload_folder(folder: str | None) -> str:
    clean_folder = (folder or "mdq_plus/general").strip().strip("/")
    if clean_folder not in _ALLOWED_FOLDERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid upload folder.",
        )
    return clean_folder


async def read_validated_upload(file: UploadFile) -> bytes:
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
    return content


async def upload_image(file: UploadFile, folder: str = "mdq_plus/general") -> str:
    """Validate and upload an image/PDF to an approved Cloudinary folder."""
    clean_folder = validate_upload_folder(folder)
    content = await read_validated_upload(file)

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
    except Exception as e:
        logger.error("Failed to upload file to Cloudinary: %s", e, exc_info=True)
        raise HTTPException(status_code=502, detail="File upload failed") from e
