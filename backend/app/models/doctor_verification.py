import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    Uuid,
    event,
)

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DoctorVerificationSubmission(Base):
    __tablename__ = "doctor_verification_submissions"
    __table_args__ = (
        CheckConstraint(
            "submission_type IN ('initial', 'reapplication', 'reverification', 'legacy_import')",
            name="ck_doctor_verification_submission_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'historical_unknown')",
            name="ck_doctor_verification_submission_status",
        ),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doctor_id = Column(
        ForeignKey("doctors.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    submission_type = Column(String(24), nullable=False)
    status = Column(String(24), nullable=False, default="pending", index=True)
    submitted_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    reviewed_by_user_id = Column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    rejection_reason = Column(String(1000), nullable=True)
    supersedes_submission_id = Column(
        ForeignKey("doctor_verification_submissions.id", ondelete="RESTRICT"),
        nullable=True,
    )

    # These are the only professional fields currently displayed in the admin
    # verification card. They are snapshots, not live Doctor profile values.
    license_number_snapshot = Column(String, nullable=False)
    specialty_snapshot = Column(String, nullable=False)


class DoctorVerificationDocument(Base):
    __tablename__ = "doctor_verification_documents"
    __table_args__ = (
        UniqueConstraint(
            "submission_id",
            "document_kind",
            name="uq_verification_document_kind_per_submission",
        ),
        CheckConstraint(
            "document_kind IN ('mdcn_license', 'indemnity_certificate')",
            name="ck_doctor_verification_document_kind",
        ),
        CheckConstraint(
            "delivery_type = 'authenticated'",
            name="ck_doctor_verification_document_delivery",
        ),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    submission_id = Column(
        ForeignKey("doctor_verification_submissions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    document_kind = Column(String(32), nullable=False)
    cloudinary_public_id = Column(String, nullable=False)
    resource_type = Column(String(16), nullable=False)
    format = Column(String(16), nullable=False)
    delivery_type = Column(String(16), nullable=False, default="authenticated")
    sha256_digest = Column(String(64), nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    mime_type = Column(String(64), nullable=False)
    uploaded_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


def _deny_document_mutation(_mapper, _connection, _target) -> None:
    raise ValueError("Committed verification documents are immutable")


# The migration enforces this in PostgreSQL. These listeners also protect
# direct ORM use and the SQLite test environment.
event.listen(DoctorVerificationDocument, "before_update", _deny_document_mutation)
event.listen(DoctorVerificationDocument, "before_delete", _deny_document_mutation)
