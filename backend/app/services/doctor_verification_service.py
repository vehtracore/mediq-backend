from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.doctor import Doctor
from app.models.doctor_verification import (
    DoctorVerificationDocument,
    DoctorVerificationSubmission,
)
from app.models.user import User
from app.services.media_service import SensitiveMediaAsset


REQUIRED_DOCUMENT_KINDS = {"mdcn_license", "indemnity_certificate"}


def _document_from_asset(
    submission_id: UUID,
    document_kind: str,
    asset: SensitiveMediaAsset,
) -> DoctorVerificationDocument:
    if (
        not asset.sha256_digest
        or asset.size_bytes is None
        or not asset.mime_type
    ):
        raise ValueError("Verification asset integrity metadata is incomplete")
    return DoctorVerificationDocument(
        submission_id=submission_id,
        document_kind=document_kind,
        cloudinary_public_id=asset.public_id,
        resource_type=asset.resource_type,
        format=asset.format,
        delivery_type=asset.delivery_type,
        sha256_digest=asset.sha256_digest,
        size_bytes=asset.size_bytes,
        mime_type=asset.mime_type,
    )


def create_submission(
    db: Session,
    *,
    doctor: Doctor,
    submission_type: str,
    license_number: str,
    specialty: str,
    mdcn_asset: SensitiveMediaAsset,
    indemnity_asset: SensitiveMediaAsset,
    supersedes_submission_id: UUID | None = None,
) -> DoctorVerificationSubmission:
    pending = (
        db.query(DoctorVerificationSubmission.id)
        .filter(
            DoctorVerificationSubmission.doctor_id == doctor.id,
            DoctorVerificationSubmission.status == "pending",
        )
        .first()
    )
    if pending is not None:
        raise HTTPException(
            status_code=409,
            detail="A verification submission is already pending review.",
        )

    if supersedes_submission_id is not None:
        superseded = (
            db.query(DoctorVerificationSubmission)
            .filter(
                DoctorVerificationSubmission.id == supersedes_submission_id,
                DoctorVerificationSubmission.doctor_id == doctor.id,
            )
            .first()
        )
        if superseded is None or superseded.status == "pending":
            raise HTTPException(status_code=400, detail="Invalid superseded submission.")

    submission = DoctorVerificationSubmission(
        doctor_id=doctor.id,
        submission_type=submission_type,
        status="pending",
        supersedes_submission_id=supersedes_submission_id,
        license_number_snapshot=license_number,
        specialty_snapshot=specialty,
    )
    db.add(submission)
    db.flush()
    db.add_all(
        [
            _document_from_asset(submission.id, "mdcn_license", mdcn_asset),
            _document_from_asset(
                submission.id,
                "indemnity_certificate",
                indemnity_asset,
            ),
        ]
    )
    return submission


def latest_terminal_submission(
    db: Session, doctor_id: int
) -> DoctorVerificationSubmission | None:
    return (
        db.query(DoctorVerificationSubmission)
        .filter(
            DoctorVerificationSubmission.doctor_id == doctor_id,
            DoctorVerificationSubmission.status.in_(("approved", "rejected")),
        )
        .order_by(DoctorVerificationSubmission.submitted_at.desc())
        .first()
    )


def decide_submission(
    db: Session,
    *,
    submission_id: UUID,
    admin: User,
    decision: str,
    rejection_reason: str | None = None,
) -> tuple[DoctorVerificationSubmission, Doctor, User]:
    if decision not in {"approved", "rejected"}:
        raise ValueError("Unsupported verification decision")
    if decision == "rejected":
        rejection_reason = (rejection_reason or "").strip()
        if not rejection_reason:
            raise HTTPException(status_code=422, detail="Rejection reason is required.")
        if len(rejection_reason) > 1000:
            raise HTTPException(status_code=422, detail="Rejection reason is too long.")
    else:
        rejection_reason = None

    reviewed_at = datetime.now(timezone.utc)
    updated = (
        db.query(DoctorVerificationSubmission)
        .filter(
            DoctorVerificationSubmission.id == submission_id,
            DoctorVerificationSubmission.status == "pending",
        )
        .update(
            {
                DoctorVerificationSubmission.status: decision,
                DoctorVerificationSubmission.reviewed_at: reviewed_at,
                DoctorVerificationSubmission.reviewed_by_user_id: admin.id,
                DoctorVerificationSubmission.rejection_reason: rejection_reason,
            },
            synchronize_session=False,
        )
    )
    if updated != 1:
        exists = (
            db.query(DoctorVerificationSubmission.id)
            .filter(DoctorVerificationSubmission.id == submission_id)
            .first()
        )
        if exists is None:
            raise HTTPException(status_code=404, detail="Verification submission not found.")
        raise HTTPException(
            status_code=409,
            detail="This verification submission has already been decided.",
        )

    submission = (
        db.query(DoctorVerificationSubmission)
        .filter(DoctorVerificationSubmission.id == submission_id)
        .populate_existing()
        .one()
    )
    doctor = db.query(Doctor).filter(Doctor.id == submission.doctor_id).one()
    user = db.query(User).filter(User.id == doctor.user_id).one()

    if decision == "approved":
        doctor.current_verification_submission_id = submission.id
        doctor.license_number = submission.license_number_snapshot
        doctor.specialty = submission.specialty_snapshot
        doctor.is_verified = True
        doctor.is_available = True
        doctor.status = "active"
        doctor.rejection_reason = None
        user.is_active = True
    elif not doctor.is_verified or doctor.status != "active":
        # This was initial onboarding (or a correction before first approval).
        doctor.is_verified = False
        doctor.is_available = False
        doctor.status = "rejected"
        doctor.rejection_reason = rejection_reason
        user.is_active = False
    # Rejected replacement evidence never alters an approved doctor's current
    # package, operational status, or activation state.

    return submission, doctor, user


def submission_documents(
    db: Session, submission_id: UUID
) -> list[DoctorVerificationDocument]:
    return (
        db.query(DoctorVerificationDocument)
        .filter(DoctorVerificationDocument.submission_id == submission_id)
        .order_by(DoctorVerificationDocument.document_kind)
        .all()
    )
