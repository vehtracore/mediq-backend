import asyncio
import hashlib
import inspect
import io
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks, FastAPI, HTTPException, Response
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.datastructures import Headers, UploadFile
from starlette.requests import Request

from app.api import deps
from app.api.v1 import admin, auth, doctors, media
from app.api.v1.appointments import require_approved_doctor
from app.core.api_errors import ApiError
from app.core.database import Base, get_db
from app.models.audit import AuditLog
from app.models.doctor import Doctor
from app.models.doctor_verification import (
    DoctorVerificationDocument,
    DoctorVerificationSubmission,
)
from app.models.user import User
from app.schemas.doctor import PublicDoctorResponse
from app.services.doctor_verification_service import create_submission, decide_submission
from app.services.media_service import SensitiveMediaAccess, SensitiveMediaAsset


PNG = b"\x89PNG\r\n\x1a\ncredential-fixture"


def _request(method="POST", path="/"):
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 1234),
            "server": ("test", 80),
            "scheme": "http",
        }
    )


def _upload(name="credential.png"):
    return UploadFile(
        io.BytesIO(PNG),
        filename=name,
        headers=Headers({"content-type": "image/png"}),
    )


def _asset(name: str, content: bytes = PNG) -> SensitiveMediaAsset:
    return SensitiveMediaAsset(
        public_id=f"mdq_plus/restricted/{name}",
        resource_type="image",
        format="png",
        delivery_type="authenticated",
        sha256_digest=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        mime_type="image/png",
    )


def _user(user_id, email, role="doctor", active=False):
    return User(
        id=user_id,
        supabase_auth_id=uuid4(),
        email=email,
        first_name="Test",
        last_name="User",
        hashed_password="SUPABASE_MANAGED",
        dob=date(1990, 1, 1),
        role=role,
        is_active=active,
        is_banned=False,
    )


@pytest.fixture()
def db_session():
    handle, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(handle)
    engine = create_engine(
        f"sqlite:///{path}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            Doctor.__table__,
            DoctorVerificationSubmission.__table__,
            DoctorVerificationDocument.__table__,
            AuditLog.__table__,
        ],
    )
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db = Session()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()
        try:
            os.remove(path)
        except PermissionError:
            pass


@pytest.fixture()
def actors(db_session):
    doctor_user = _user(1, "doctor@example.test")
    other_doctor = _user(2, "other@example.test", active=True)
    patient = _user(3, "patient@example.test", role="patient", active=True)
    admin_user = _user(4, "admin@example.test", role="admin", active=True)
    db_session.add_all([doctor_user, other_doctor, patient, admin_user])
    db_session.flush()
    doctor = Doctor(
        user_id=doctor_user.id,
        full_name="Dr Evidence",
        specialty="General",
        license_number="MDCN-100",
        status="pending",
        is_verified=False,
        is_available=False,
    )
    db_session.add(doctor)
    db_session.flush()
    submission = create_submission(
        db_session,
        doctor=doctor,
        submission_type="initial",
        license_number=doctor.license_number,
        specialty=doctor.specialty,
        mdcn_asset=_asset("license-v1"),
        indemnity_asset=_asset("indemnity-v1"),
    )
    db_session.commit()
    return doctor_user, other_doctor, patient, admin_user, doctor, submission


def test_initial_registration_creates_pending_submission_documents_and_digests(db_session):
    identity_id = uuid4()
    identity = deps.SupabaseIdentity(
        auth_id=identity_id,
        email="new-doctor@example.test",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    assets = [_asset("registration-license"), _asset("registration-indemnity")]
    with patch.object(auth, "upload_sensitive_media", side_effect=assets):
        created = asyncio.run(
            inspect.unwrap(auth.register_doctor)(
                request=_request(path="/api/v1/auth/doctor/register"),
                background_tasks=BackgroundTasks(),
                email=identity.email,
                full_name="Dr New",
                specialty="Cardiology",
                license_number="MDCN-NEW",
                mdcn_license=_upload("license.png"),
                indemnity_certificate=_upload("indemnity.png"),
                db=db_session,
                identity=identity,
            )
        )

    doctor = db_session.query(Doctor).filter(Doctor.user_id == created.id).one()
    submission = db_session.query(DoctorVerificationSubmission).one()
    documents = db_session.query(DoctorVerificationDocument).all()
    assert submission.doctor_id == doctor.id
    assert submission.status == "pending"
    assert submission.submission_type == "initial"
    assert {item.document_kind for item in documents} == {
        "mdcn_license",
        "indemnity_certificate",
    }
    assert all(len(item.sha256_digest) == 64 for item in documents)
    assert doctor.is_verified is False and doctor.status == "pending"
    assert created.is_active is False


def test_public_doctor_response_exposes_no_evidence_metadata(actors):
    *_, doctor, submission = actors
    data = PublicDoctorResponse.model_validate(doctor).model_dump()
    serialized = repr(data)
    assert str(submission.id) not in serialized
    for field in (
        "current_verification_submission_id",
        "sha256_digest",
        "cloudinary_public_id",
        "rejection_reason",
        "reviewed_by_user_id",
    ):
        assert field not in data


def test_admin_can_read_exact_pending_submission(actors, db_session):
    *_, admin_user, doctor, submission = actors
    result = admin.get_verification_submission(submission.id, db_session, admin_user)
    assert result["id"] == submission.id
    assert result["doctor_id"] == doctor.id
    assert len(result["documents"]) == 2
    assert all(item.sha256_digest for item in result["documents"])
    assert all(not hasattr(item, "url") for item in result["documents"])


def test_patient_and_unrelated_doctor_cannot_access_submission_admin_api(actors):
    _, other_doctor, patient, _, _, _ = actors
    for caller in (patient, other_doctor):
        with pytest.raises(HTTPException) as raised:
            admin.get_current_admin(caller)
        assert raised.value.status_code == 403


def test_versioned_document_access_is_owner_or_admin_only(actors, db_session):
    owner, other_doctor, patient, admin_user, _, submission = actors
    document = db_session.query(DoctorVerificationDocument).filter(
        DoctorVerificationDocument.submission_id == submission.id
    ).first()
    endpoint = inspect.unwrap(media.access_verification_document)
    signed = SensitiveMediaAccess(
        url="https://api.cloudinary.test/private?signed=true",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        expires_in=300,
    )
    with patch.object(media.media_service, "generate_sensitive_access", return_value=signed):
        for caller in (owner, admin_user):
            result = endpoint(
                request=_request("GET"),
                response=Response(),
                document_id=document.id,
                db=db_session,
                current_user=caller,
            )
            assert result.expires_in == 300
        for caller in (patient, other_doctor):
            with pytest.raises(ApiError) as raised:
                endpoint(
                    request=_request("GET"),
                    response=Response(),
                    document_id=document.id,
                    db=db_session,
                    current_user=caller,
                )
            assert raised.value.status_code == 404


def test_verification_document_access_requires_authentication():
    app = FastAPI()
    app.include_router(media.router, prefix="/media")
    app.dependency_overrides[get_db] = lambda: iter([None])
    response = TestClient(app).get(
        f"/media/verification-documents/{uuid4()}/access"
    )
    assert response.status_code == 401


def test_approval_binds_exact_submission_reviewer_and_activates_initial_doctor(actors, db_session):
    doctor_user, _, _, admin_user, doctor, submission = actors
    decided, _, _ = decide_submission(
        db_session,
        submission_id=submission.id,
        admin=admin_user,
        decision="approved",
    )
    db_session.commit()
    assert decided.status == "approved"
    assert decided.reviewed_by_user_id == admin_user.id
    assert decided.reviewed_at is not None
    assert doctor.current_verification_submission_id == submission.id
    assert doctor.is_verified is True and doctor.status == "active"
    assert doctor_user.is_active is True


def test_rejection_binds_submission_and_does_not_activate_initial_doctor(actors, db_session):
    doctor_user, _, _, admin_user, doctor, submission = actors
    decided, _, _ = decide_submission(
        db_session,
        submission_id=submission.id,
        admin=admin_user,
        decision="rejected",
        rejection_reason="Unreadable document",
    )
    db_session.commit()
    assert decided.status == "rejected"
    assert decided.rejection_reason == "Unreadable document"
    assert doctor.current_verification_submission_id is None
    assert doctor.is_verified is False and doctor.status == "rejected"
    assert doctor_user.is_active is False


def test_second_or_contradictory_review_is_rejected(actors, db_session):
    *_, admin_user, _, submission = actors
    decide_submission(
        db_session,
        submission_id=submission.id,
        admin=admin_user,
        decision="approved",
    )
    db_session.commit()
    with pytest.raises(HTTPException) as raised:
        decide_submission(
            db_session,
            submission_id=submission.id,
            admin=admin_user,
            decision="rejected",
            rejection_reason="Too late",
        )
    assert raised.value.status_code == 409


def test_rejected_submission_is_immutable_and_correction_is_new(actors, db_session):
    _, _, _, admin_user, doctor, first = actors
    decide_submission(
        db_session,
        submission_id=first.id,
        admin=admin_user,
        decision="rejected",
        rejection_reason="Replace both files",
    )
    db_session.commit()
    first_document_ids = {
        item.id
        for item in db_session.query(DoctorVerificationDocument).filter(
            DoctorVerificationDocument.submission_id == first.id
        )
    }
    second = create_submission(
        db_session,
        doctor=doctor,
        submission_type="reapplication",
        license_number="MDCN-100-CORRECTED",
        specialty=doctor.specialty,
        mdcn_asset=_asset("license-v2", PNG + b"v2"),
        indemnity_asset=_asset("indemnity-v2", PNG + b"v2"),
        supersedes_submission_id=first.id,
    )
    db_session.commit()
    assert second.id != first.id and second.status == "pending"
    assert second.supersedes_submission_id == first.id
    assert db_session.query(DoctorVerificationSubmission).count() == 2
    assert first_document_ids.issubset(
        {item.id for item in db_session.query(DoctorVerificationDocument)}
    )
    assert first.status == "rejected"


def test_supported_reapplication_endpoint_commits_new_document_package(actors, db_session):
    doctor_user, _, _, admin_user, doctor, first = actors
    decide_submission(
        db_session,
        submission_id=first.id,
        admin=admin_user,
        decision="rejected",
        rejection_reason="Correct and resubmit",
    )
    db_session.commit()
    replacements = [
        _asset("endpoint-license-v2", PNG + b"license-v2"),
        _asset("endpoint-indemnity-v2", PNG + b"indemnity-v2"),
    ]
    with patch.object(doctors, "upload_sensitive_media", side_effect=replacements):
        result = asyncio.run(
            inspect.unwrap(doctors.reapply_for_verification)(
                license_number="MDCN-100-CORRECTED",
                mdcn_license=_upload("license-v2.png"),
                indemnity_certificate=_upload("indemnity-v2.png"),
                db=db_session,
                current_user=doctor_user,
            )
        )

    second = db_session.query(DoctorVerificationSubmission).filter(
        DoctorVerificationSubmission.id == result["submission_id"]
    ).one()
    assert second.id != first.id
    assert second.supersedes_submission_id == first.id
    assert second.status == "pending" and doctor.status == "pending"
    assert db_session.query(DoctorVerificationDocument).filter(
        DoctorVerificationDocument.submission_id == second.id
    ).count() == 2
    assert db_session.query(DoctorVerificationDocument).filter(
        DoctorVerificationDocument.submission_id == first.id
    ).count() == 2


def test_committed_document_rows_cannot_be_updated_or_deleted(actors, db_session):
    *_, submission = actors
    document = db_session.query(DoctorVerificationDocument).filter(
        DoctorVerificationDocument.submission_id == submission.id
    ).first()
    document.cloudinary_public_id = "attacker/substitution"
    with pytest.raises(ValueError):
        db_session.commit()
    db_session.rollback()
    document = db_session.query(DoctorVerificationDocument).filter(
        DoctorVerificationDocument.submission_id == submission.id
    ).first()
    db_session.delete(document)
    with pytest.raises(ValueError):
        db_session.commit()


def _approve_initial(db_session, actors):
    doctor_user, _, _, admin_user, doctor, first = actors
    decide_submission(
        db_session,
        submission_id=first.id,
        admin=admin_user,
        decision="approved",
    )
    db_session.commit()
    return doctor_user, admin_user, doctor, first


def test_approved_doctor_stays_active_and_current_while_reverification_pending(actors, db_session):
    doctor_user, _, doctor, first = _approve_initial(db_session, actors)
    second = create_submission(
        db_session,
        doctor=doctor,
        submission_type="reverification",
        license_number="MDCN-100-RENEWED",
        specialty=doctor.specialty,
        mdcn_asset=_asset("license-v2"),
        indemnity_asset=_asset("indemnity-v2"),
        supersedes_submission_id=first.id,
    )
    db_session.commit()
    assert second.status == "pending"
    assert doctor.current_verification_submission_id == first.id
    assert doctor.is_verified and doctor.status == "active" and doctor_user.is_active


def test_approving_reverification_switches_pointer_and_retains_history(actors, db_session):
    _, admin_user, doctor, first = _approve_initial(db_session, actors)
    second = create_submission(
        db_session,
        doctor=doctor,
        submission_type="reverification",
        license_number="MDCN-100-RENEWED",
        specialty=doctor.specialty,
        mdcn_asset=_asset("license-v2"),
        indemnity_asset=_asset("indemnity-v2"),
        supersedes_submission_id=first.id,
    )
    db_session.commit()
    decide_submission(
        db_session,
        submission_id=second.id,
        admin=admin_user,
        decision="approved",
    )
    db_session.commit()
    assert doctor.current_verification_submission_id == second.id
    assert first.status == "approved"
    assert db_session.query(DoctorVerificationSubmission).count() == 2
    assert db_session.query(DoctorVerificationDocument).count() == 4


def test_rejecting_reverification_leaves_prior_approval_and_activation(actors, db_session):
    doctor_user, admin_user, doctor, first = _approve_initial(db_session, actors)
    second = create_submission(
        db_session,
        doctor=doctor,
        submission_type="reverification",
        license_number="MDCN-100-RENEWED",
        specialty=doctor.specialty,
        mdcn_asset=_asset("license-v2"),
        indemnity_asset=_asset("indemnity-v2"),
        supersedes_submission_id=first.id,
    )
    db_session.commit()
    decide_submission(
        db_session,
        submission_id=second.id,
        admin=admin_user,
        decision="rejected",
        rejection_reason="Renewal not acceptable",
    )
    db_session.commit()
    assert doctor.current_verification_submission_id == first.id
    assert doctor.is_verified and doctor.status == "active" and doctor_user.is_active
    assert second.status == "rejected" and first.status == "approved"


def test_reviewer_and_status_fields_cannot_be_overposted():
    with pytest.raises(ValidationError):
        admin.RejectDoctorRequest.model_validate(
            {
                "rejection_reason": "No",
                "status": "approved",
                "reviewed_by_user_id": 999,
                "reviewed_at": "2026-01-01T00:00:00Z",
            }
        )
    signature = inspect.signature(inspect.unwrap(admin.approve_verification_submission))
    assert "payload" not in signature.parameters


def test_arbitrary_storage_id_signing_is_not_accepted():
    signature = inspect.signature(inspect.unwrap(media.access_verification_document))
    assert "document_id" in signature.parameters
    assert "public_id" not in signature.parameters


def test_legacy_approved_doctor_without_history_still_operates(db_session):
    legacy_user = _user(20, "legacy@example.test", active=True)
    db_session.add(legacy_user)
    db_session.flush()
    legacy = Doctor(
        user_id=legacy_user.id,
        full_name="Dr Legacy",
        specialty="General",
        license_number="LEGACY-1",
        is_verified=True,
        status="active",
    )
    db_session.add(legacy)
    db_session.commit()
    assert require_approved_doctor(legacy_user, db_session).id == legacy.id
    assert legacy.current_verification_submission_id is None
    assert db_session.query(DoctorVerificationSubmission).count() == 0


def test_no_fake_legacy_reviewer_or_timestamp_is_generated(db_session):
    legacy_user = _user(21, "legacy-unknown@example.test", active=True)
    db_session.add(legacy_user)
    db_session.flush()
    legacy = Doctor(
        user_id=legacy_user.id,
        full_name="Dr Unknown",
        specialty="General",
        license_number="LEGACY-2",
        is_verified=True,
        status="active",
    )
    db_session.add(legacy)
    db_session.commit()
    assert db_session.query(DoctorVerificationSubmission).filter(
        DoctorVerificationSubmission.doctor_id == legacy.id
    ).all() == []


def test_rejected_legacy_doctor_reverification_does_not_deactivate(db_session):
    legacy_user = _user(22, "legacy-renewal@example.test", active=True)
    admin_user = _user(23, "legacy-admin@example.test", role="admin", active=True)
    db_session.add_all([legacy_user, admin_user])
    db_session.flush()
    legacy = Doctor(
        user_id=legacy_user.id,
        full_name="Dr Legacy Renewal",
        specialty="General",
        license_number="LEGACY-3",
        is_verified=True,
        is_available=True,
        status="active",
    )
    db_session.add(legacy)
    db_session.flush()
    replacement = create_submission(
        db_session,
        doctor=legacy,
        submission_type="reverification",
        license_number="LEGACY-3-RENEWED",
        specialty=legacy.specialty,
        mdcn_asset=_asset("legacy-license-renewal"),
        indemnity_asset=_asset("legacy-indemnity-renewal"),
    )
    db_session.commit()
    decide_submission(
        db_session,
        submission_id=replacement.id,
        admin=admin_user,
        decision="rejected",
        rejection_reason="Replacement rejected",
    )
    db_session.commit()
    assert legacy.current_verification_submission_id is None
    assert legacy.is_verified and legacy.status == "active" and legacy_user.is_active
