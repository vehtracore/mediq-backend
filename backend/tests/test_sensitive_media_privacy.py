import asyncio
import hashlib
import inspect
import io
import logging
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException, Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.datastructures import Headers, UploadFile
from starlette.requests import Request

from app.api.v1 import chat, media
from app.core.api_errors import ApiError
from app.core.database import Base, get_db
from app.models.doctor import Doctor
from app.models.lab_result import LabResult
from app.models.user import User
from app.schemas.doctor import DoctorResponse, PublicDoctorResponse, ReapplyRequest
from app.schemas.lab import LabResultOut
from app.services import media_service


PNG = b"\x89PNG\r\n\x1a\n" + b"fixture"


def _request(method: str = "GET", path: str = "/") -> Request:
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


def _upload(content: bytes = PNG, filename: str = "scan.png") -> UploadFile:
    return UploadFile(
        io.BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": "image/png"}),
    )


def _user(user_id: int, email: str, role: str = "patient") -> User:
    return User(
        id=user_id,
        email=email,
        first_name="Test",
        last_name="User",
        dob=date(1990, 1, 1),
        role=role,
        is_active=True,
        is_banned=False,
    )


@pytest.fixture()
def db_session():
    handle, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(handle)
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(
        engine,
        tables=[User.__table__, Doctor.__table__, LabResult.__table__],
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
def media_records(db_session):
    owner = _user(1, "owner@example.test")
    other_patient = _user(2, "other@example.test")
    doctor_user = _user(3, "doctor@example.test", "doctor")
    other_doctor = _user(4, "other-doctor@example.test", "doctor")
    admin = _user(5, "admin@example.test", "admin")
    db_session.add_all([owner, other_patient, doctor_user, other_doctor, admin])
    db_session.flush()
    doctor = Doctor(
        user_id=doctor_user.id,
        full_name="Doctor Owner",
        specialty="General",
        license_number="MDCN-1",
        is_verified=False,
        status="pending",
        mdcn_license_public_id="mdq_plus/doctor_licenses/private-license",
        mdcn_license_resource_type="image",
        mdcn_license_format="png",
        mdcn_license_delivery_type="authenticated",
        indemnity_cert_public_id="mdq_plus/indemnity_certs/private-indemnity",
        indemnity_cert_resource_type="image",
        indemnity_cert_format="pdf",
        indemnity_cert_delivery_type="authenticated",
    )
    db_session.add(doctor)
    db_session.flush()
    lab_record = LabResult(
        user_id=owner.id,
        image_url=None,
        image_public_id="mediq_lab_scans/private-scan",
        image_resource_type="image",
        image_format="png",
        image_delivery_type="authenticated",
        raw_data={"status": "SUCCESS"},
        is_verified=False,
    )
    db_session.add(lab_record)
    db_session.commit()
    return owner, other_patient, doctor_user, other_doctor, admin, doctor, lab_record


def _signed_access() -> media_service.SensitiveMediaAccess:
    return media_service.SensitiveMediaAccess(
        url="https://api.cloudinary.test/download?signed=redacted",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        expires_in=300,
    )


def test_sensitive_access_routes_require_authentication():
    app = FastAPI()
    app.include_router(media.router, prefix="/media")

    def override_db():
        yield None

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    assert (
        client.get("/media/doctor-documents/1/mdcn-license/access").status_code
        == 401
    )
    assert client.get("/media/lab-images/1/access").status_code == 401


def test_submitting_doctor_and_admin_can_access_verification_documents(
    db_session, media_records
):
    _, _, doctor_user, _, admin, doctor, _ = media_records
    endpoint = inspect.unwrap(media.access_doctor_document)
    with patch.object(
        media.media_service,
        "generate_sensitive_access",
        return_value=_signed_access(),
    ):
        for caller in (doctor_user, admin):
            response = Response()
            result = endpoint(
                request=_request(path="/media/doctor-documents"),
                response=response,
                doctor_id=doctor.id,
                document_kind="mdcn-license",
                db=db_session,
                current_user=caller,
            )
            assert result.expires_in == 300
            assert result.url.startswith("https://api.cloudinary.test/")
            assert response.headers["cache-control"] == "no-store, private"


def test_patient_and_unrelated_doctor_cannot_access_doctor_documents(
    db_session, media_records
):
    owner, _, _, other_doctor, _, doctor, _ = media_records
    endpoint = inspect.unwrap(media.access_doctor_document)
    for caller in (owner, other_doctor):
        with pytest.raises(ApiError) as raised:
            endpoint(
                request=_request(),
                response=Response(),
                doctor_id=doctor.id,
                document_kind="mdcn-license",
                db=db_session,
                current_user=caller,
            )
        assert raised.value.status_code == 404


def test_lab_image_access_is_owner_bound_and_doctors_are_denied_without_link(
    db_session, media_records
):
    owner, other_patient, doctor_user, other_doctor, _, _, record = media_records
    endpoint = inspect.unwrap(media.access_lab_image)
    with patch.object(
        media.media_service,
        "generate_sensitive_access",
        return_value=_signed_access(),
    ):
        result = endpoint(
            request=_request(),
            response=Response(),
            record_id=record.id,
            db=db_session,
            current_user=owner,
        )
    assert result.expires_in == 300

    for caller in (other_patient, doctor_user, other_doctor):
        with pytest.raises(ApiError) as raised:
            endpoint(
                request=_request(),
                response=Response(),
                record_id=record.id,
                db=db_session,
                current_user=caller,
            )
        assert raised.value.status_code == 404


def test_public_and_private_api_schemas_never_serialize_storage_references(
    media_records,
):
    *_, doctor, record = media_records
    private_data = DoctorResponse.model_validate(doctor).model_dump()
    public_data = PublicDoctorResponse.model_validate(doctor).model_dump()
    lab_data = LabResultOut.model_validate(record).model_dump()

    for data in (private_data, public_data):
        assert "mdcn_license_url" not in data
        assert "indemnity_cert_url" not in data
        assert "mdcn_license_public_id" not in data
        assert "indemnity_cert_public_id" not in data
    assert "image_url" not in lab_data
    assert "image_public_id" not in lab_data
    assert private_data["mdcn_license_available"] is True
    assert "mdcn_license_available" not in public_data


def test_reapply_contract_rejects_caller_supplied_document_urls():
    with pytest.raises(Exception):
        ReapplyRequest.model_validate(
            {"mdcn_license_url": "https://attacker.example/pretend-license.png"}
        )


def test_access_endpoint_cannot_sign_an_arbitrary_public_id():
    signature = inspect.signature(inspect.unwrap(media.access_doctor_document))
    assert "public_id" not in signature.parameters
    signature = inspect.signature(inspect.unwrap(media.access_lab_image))
    assert "public_id" not in signature.parameters


def test_signed_access_is_authenticated_and_short_lived():
    asset = media_service.SensitiveMediaAsset(
        public_id="restricted/asset",
        resource_type="image",
        format="png",
    )
    with (
        patch.object(media_service.time, "time", return_value=1_000),
        patch.object(
            media_service.cloudinary.utils,
            "private_download_url",
            return_value="https://api.cloudinary.test/download?signature=safe",
        ) as signer,
    ):
        access = media_service.generate_sensitive_access(asset)

    assert access.expires_in == 300
    assert int(access.expires_at.timestamp()) == 1_300
    assert signer.call_args.kwargs["type"] == "authenticated"
    assert signer.call_args.kwargs["expires_at"] == 1_300


def test_legacy_public_record_is_not_returned_as_an_access_url(
    db_session, media_records
):
    *_, doctor, _ = media_records
    doctor.mdcn_license_public_id = None
    doctor.mdcn_license_url = "https://res.cloudinary.com/example/image/upload/old.png"
    db_session.commit()

    with pytest.raises(ApiError) as raised:
        inspect.unwrap(media.access_doctor_document)(
            request=_request(),
            response=Response(),
            doctor_id=doctor.id,
            document_kind="mdcn-license",
            db=db_session,
            current_user=media_records[4],
        )
    assert raised.value.status_code == 409
    assert "cloudinary" not in raised.value.safe_message.lower()


def test_sensitive_upload_uses_server_namespace_and_authenticated_delivery():
    provider_result = {
        "public_id": "mdq_plus/doctor_licenses/generated",
        "resource_type": "image",
        "format": "png",
        "secure_url": "https://should-not-be-stored.example/public",
    }
    with patch.object(
        media_service.cloudinary.uploader,
        "upload",
        return_value=provider_result,
    ) as uploader:
        asset = asyncio.run(
            media_service.upload_sensitive_media(
                _upload(),
                media_class="doctor_license",
            )
        )

    assert asset.public_id == provider_result["public_id"]
    assert asset.sha256_digest == hashlib.sha256(PNG).hexdigest()
    assert asset.size_bytes == len(PNG)
    assert asset.mime_type == "image/png"
    assert uploader.call_args.kwargs["folder"] == "mdq_plus/doctor_licenses"
    assert uploader.call_args.kwargs["type"] == "authenticated"
    assert "public_id" not in uploader.call_args.kwargs
    assert "filename" not in uploader.call_args.kwargs


def test_sensitive_upload_rejects_spoofed_oversized_and_traversal_files():
    invalid_files = [
        _upload(b"<script>not an image</script>"),
        _upload(PNG + b"x" * (5 * 1024 * 1024)),
        _upload(PNG, filename="../license.png"),
    ]
    expected = [400, 413, 400]
    for upload, status_code in zip(invalid_files, expected):
        with pytest.raises(HTTPException) as raised:
            asyncio.run(
                media_service.upload_sensitive_media(
                    upload,
                    media_class="doctor_license",
                )
            )
        assert raised.value.status_code == status_code


def test_provider_failure_is_safe_and_does_not_log_sensitive_values(caplog):
    leaked = "https://res.cloudinary.com/account/image/upload/private-id?secret=x"
    caplog.set_level(logging.ERROR)
    with patch.object(
        media_service.cloudinary.uploader,
        "upload",
        side_effect=RuntimeError(leaked),
    ):
        with pytest.raises(ApiError) as raised:
            asyncio.run(
                media_service.upload_sensitive_media(
                    _upload(),
                    media_class="lab_image",
                )
            )
    assert raised.value.code == "media_upload_unavailable"
    assert leaked not in caplog.text
    assert "private-id" not in caplog.text


def test_transient_ai_image_is_authenticated_and_returns_expiring_preview():
    user = _user(77, "ai@example.test")
    access = media_service.SensitiveMediaAccess(
        url="https://api.cloudinary.test/download?signature=temporary",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        expires_in=900,
    )
    with (
        patch.object(chat, "require_active_ai_consent"),
        patch.object(
            chat.cloudinary.uploader,
            "upload",
            return_value={
                "public_id": "mediq_ai_temp/77/generated",
                "format": "png",
            },
        ) as uploader,
        patch.object(chat, "generate_sensitive_access", return_value=access),
    ):
        result = asyncio.run(
            inspect.unwrap(chat.upload_temporary_chat_image)(
                request=_request("POST", "/chat/image"),
                file=_upload(),
                current_user=user,
            )
        )

    assert uploader.call_args.kwargs["type"] == "authenticated"
    assert result.expires_at == access.expires_at
    assert result.format == "png"
    assert result.public_id.startswith("mediq_ai_temp/77/")


def test_transient_cleanup_uses_authenticated_delivery_without_logging_id(caplog):
    caplog.set_level(logging.ERROR)
    with patch.object(
        chat.cloudinary.uploader,
        "destroy",
        return_value={"result": "ok"},
    ) as destroy:
        assert chat._delete_temp_image("mediq_ai_temp/9/secret-id", 9) is True
    assert destroy.call_args.kwargs["type"] == "authenticated"
    assert "secret-id" not in caplog.text
