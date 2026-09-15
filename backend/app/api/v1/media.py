from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api import deps
from app.core.api_errors import ApiError
from app.core.database import get_db
from app.core.limiter import limiter
from app.models.doctor import Doctor
from app.models.doctor_verification import (
    DoctorVerificationDocument,
    DoctorVerificationSubmission,
)
from app.models.lab_result import LabResult
from app.models.user import User
from app.services import media_service

router = APIRouter()


class SensitiveMediaAccessResponse(BaseModel):
    url: str
    expires_at: datetime
    expires_in: int
    format: str


def _access_response(
    asset: media_service.SensitiveMediaAsset,
) -> SensitiveMediaAccessResponse:
    access = media_service.generate_sensitive_access(asset)
    return SensitiveMediaAccessResponse(
        url=access.url,
        expires_at=access.expires_at,
        expires_in=access.expires_in,
        format=asset.format,
    )


def _doctor_document_asset(
    doctor: Doctor,
    document_kind: Literal["mdcn-license", "indemnity-certificate"],
) -> media_service.SensitiveMediaAsset:
    if document_kind == "mdcn-license":
        values = (
            doctor.mdcn_license_public_id,
            doctor.mdcn_license_resource_type,
            doctor.mdcn_license_format,
            doctor.mdcn_license_delivery_type,
        )
        legacy_url = doctor.mdcn_license_url or doctor.documents_url
    else:
        values = (
            doctor.indemnity_cert_public_id,
            doctor.indemnity_cert_resource_type,
            doctor.indemnity_cert_format,
            doctor.indemnity_cert_delivery_type,
        )
        legacy_url = doctor.indemnity_cert_url

    if not all(values):
        if legacy_url:
            raise ApiError(
                409,
                "media_migration_required",
                "This file is awaiting secure-media migration.",
            )
        raise ApiError(404, "media_not_found", "The requested file was not found.")
    return media_service.SensitiveMediaAsset(
        public_id=values[0],
        resource_type=values[1],
        format=values[2],
        delivery_type=values[3],
    )


@router.get(
    "/doctor-documents/{doctor_id}/{document_kind}/access",
    response_model=SensitiveMediaAccessResponse,
)
@limiter.limit("60/minute")
def access_doctor_document(
    request: Request,
    response: Response,
    doctor_id: int,
    document_kind: Literal["mdcn-license", "indemnity-certificate"],
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """Issue access only for the submitting doctor or an MDQ+ admin."""
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if doctor is None or not (
        current_user.role == "admin" or doctor.user_id == current_user.id
    ):
        raise ApiError(404, "media_not_found", "The requested file was not found.")

    response.headers["Cache-Control"] = "no-store, private"
    return _access_response(_doctor_document_asset(doctor, document_kind))


@router.get(
    "/verification-documents/{document_id}/access",
    response_model=SensitiveMediaAccessResponse,
)
@limiter.limit("60/minute")
def access_verification_document(
    request: Request,
    response: Response,
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """Resolve one logical evidence document, then issue short-lived access."""
    record = (
        db.query(DoctorVerificationDocument, DoctorVerificationSubmission, Doctor)
        .join(
            DoctorVerificationSubmission,
            DoctorVerificationSubmission.id
            == DoctorVerificationDocument.submission_id,
        )
        .join(Doctor, Doctor.id == DoctorVerificationSubmission.doctor_id)
        .filter(DoctorVerificationDocument.id == document_id)
        .first()
    )
    if record is None:
        raise ApiError(404, "media_not_found", "The requested file was not found.")
    document, _submission, doctor = record
    if current_user.role != "admin" and not (
        current_user.role == "doctor" and doctor.user_id == current_user.id
    ):
        raise ApiError(404, "media_not_found", "The requested file was not found.")

    response.headers["Cache-Control"] = "no-store, private"
    return _access_response(
        media_service.SensitiveMediaAsset(
            public_id=document.cloudinary_public_id,
            resource_type=document.resource_type,
            format=document.format,
            delivery_type=document.delivery_type,
        )
    )


@router.get(
    "/lab-images/{record_id}/access",
    response_model=SensitiveMediaAccessResponse,
)
@limiter.limit("60/minute")
def access_lab_image(
    request: Request,
    response: Response,
    record_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """Issue access for the owning patient; no record/appointment link exists."""
    record = db.query(LabResult).filter(LabResult.id == record_id).first()
    if (
        record is None
        or current_user.role != "patient"
        or record.user_id != current_user.id
    ):
        raise ApiError(404, "media_not_found", "The requested file was not found.")

    values = (
        record.image_public_id,
        record.image_resource_type,
        record.image_format,
        record.image_delivery_type,
    )
    if not all(values):
        if record.image_url:
            raise ApiError(
                409,
                "media_migration_required",
                "This file is awaiting secure-media migration.",
            )
        raise ApiError(404, "media_not_found", "The requested file was not found.")

    response.headers["Cache-Control"] = "no-store, private"
    return _access_response(
        media_service.SensitiveMediaAsset(
            public_id=values[0],
            resource_type=values[1],
            format=values[2],
            delivery_type=values[3],
        )
    )


@router.post("/upload")
@limiter.limit("20/hour")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(deps.get_current_user),
):
    """
    Authenticated media upload.

    The shared media service enforces allowed folders, file types, and size
    limits before any Cloudinary API call is made.
    """
    # The client cannot select privileged verification-document namespaces.
    url = await media_service.upload_image(
        file,
        "mdq_plus/general",
        allowed_types={"image/jpeg", "image/png", "image/webp"},
    )
    return {"url": url}
