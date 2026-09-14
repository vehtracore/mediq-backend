import asyncio
import inspect
import io
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
import jwt
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.websockets import WebSocketDisconnect

from app.api import deps
from app.api.v1 import admin, auth, chat_socket, family, media, notifications
from app.api.v1.appointments import require_approved_doctor
from app.core.database import Base, get_db
from app.models.appointment import Appointment, DoctorSlot
from app.models.doctor import Doctor
from app.models.user import User
from app.schemas.doctor import PublicDoctorResponse
from app.schemas.user import UserCreate, UserUpdate
from app.services.appointment_access import require_consultation_access
from app.services.media_service import read_validated_upload
from starlette.datastructures import UploadFile


def _request(path: str = "/api/v1/auth/signup") -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 1234),
            "server": ("test", 80),
            "scheme": "http",
        }
    )


@pytest.fixture()
def db_session():
    handle, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(handle)
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
    )
    tables = [
        User.__table__,
        Doctor.__table__,
        DoctorSlot.__table__,
        Appointment.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
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


def _user(user_id: int, email: str, role: str = "patient", **values) -> User:
    defaults = {
        "id": user_id,
        "email": email,
        "first_name": "Test",
        "last_name": "User",
        "dob": date(1990, 1, 1),
        "role": role,
        "is_active": True,
        "is_banned": False,
    }
    defaults.update(values)
    return User(**defaults)


def test_public_signup_schema_rejects_role_escalation_and_unknown_owner_fields():
    with pytest.raises(ValidationError):
        UserCreate.model_validate(
            {
                "email": "patient@example.com",
                "first_name": "Pat",
                "last_name": "Ient",
                "dob": "1990-01-01",
                "role": "admin",
            }
        )
    with pytest.raises(ValidationError):
        UserUpdate.model_validate({"role": "admin", "plan": "family"})


def test_signup_uses_verified_subject_email_and_forces_patient_role(db_session):
    auth_id = uuid4()
    identity = deps.SupabaseIdentity(
        auth_id=auth_id,
        email="patient@example.com",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    payload = UserCreate(
        email="patient@example.com",
        first_name="Pat",
        last_name="Ient",
        dob=date(1990, 1, 1),
    )
    endpoint = inspect.unwrap(auth.create_user)

    with patch.object(auth, "send_email"):
        created = endpoint(
            request=_request(),
            user=payload,
            background_tasks=BackgroundTasks(),
            db=db_session,
            identity=identity,
        )

    assert created.role == "patient"
    assert created.email == identity.email
    assert created.supabase_auth_id == auth_id


def test_signup_cannot_provision_a_different_authenticated_email(db_session):
    payload = UserCreate(
        email="victim@example.com",
        first_name="Pat",
        last_name="Ient",
        dob=date(1990, 1, 1),
    )
    identity = deps.SupabaseIdentity(
        auth_id=uuid4(),
        email="attacker@example.com",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    with pytest.raises(HTTPException) as raised:
        inspect.unwrap(auth.create_user)(
            request=_request(),
            user=payload,
            background_tasks=BackgroundTasks(),
            db=db_session,
            identity=identity,
        )
    assert raised.value.status_code == 403


def test_local_identity_is_resolved_by_immutable_supabase_subject(db_session):
    auth_id = uuid4()
    account = _user(
        1,
        "old-email@example.com",
        supabase_auth_id=auth_id,
    )
    db_session.add(account)
    db_session.commit()
    identity = deps.SupabaseIdentity(
        auth_id=auth_id,
        email="new-email@example.com",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )

    with patch.object(deps, "get_supabase_identity", return_value=identity):
        resolved = deps.get_current_user(token="signed-token", db=db_session)

    assert resolved.id == account.id


def test_bound_email_row_cannot_be_claimed_by_another_supabase_subject(db_session):
    account = _user(
        1,
        "victim@example.com",
        supabase_auth_id=uuid4(),
    )
    db_session.add(account)
    db_session.commit()
    identity = deps.SupabaseIdentity(
        auth_id=uuid4(),
        email="victim@example.com",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )

    with patch.object(deps, "get_supabase_identity", return_value=identity):
        with pytest.raises(HTTPException) as raised:
            deps.get_current_user(token="signed-token", db=db_session)

    assert raised.value.status_code == 401


def test_expired_supabase_token_is_rejected_as_unauthenticated():
    with (
        patch.object(deps.jwks_client, "get_signing_key_from_jwt") as key,
        patch.object(jwt, "decode", side_effect=jwt.ExpiredSignatureError()),
    ):
        key.return_value.key = object()
        with pytest.raises(HTTPException) as raised:
            deps.get_supabase_identity("expired-token")

    assert raised.value.status_code == 401


def test_public_doctor_contract_omits_private_verification_and_payout_fields():
    doctor = SimpleNamespace(
        id=7,
        user_id=9,
        full_name="Dr Public",
        specialty="General",
        bio=None,
        image_url=None,
        hourly_rate=4000,
        consultation_fee=4000,
        consultation_duration_minutes=30,
        rating=5,
        review_count=0,
        years_experience=3,
        is_available=True,
        is_verified=True,
        license_number="PRIVATE",
        mdcn_license_url="https://private.example/license.pdf",
        indemnity_cert_url="https://private.example/indemnity.pdf",
        bank_code="999",
        account_number="0123456789",
        paystack_subaccount_code="ACCT_private",
        paystack_recipient_code="RCP_private",
    )
    data = PublicDoctorResponse.model_validate(doctor).model_dump()
    for private_field in {
        "user_id",
        "license_number",
        "mdcn_license_url",
        "indemnity_cert_url",
        "bank_code",
        "account_number",
        "paystack_subaccount_code",
        "paystack_recipient_code",
    }:
        assert private_field not in data


def test_patient_cannot_use_doctor_route_even_if_stale_doctor_row_exists(db_session):
    patient = _user(1, "patient@example.test", role="patient")
    db_session.add(patient)
    db_session.flush()
    db_session.add(
        Doctor(
            user_id=patient.id,
            full_name="Stale Row",
            specialty="General",
            license_number="STALE-1",
            is_verified=True,
            status="active",
        )
    )
    db_session.commit()

    with pytest.raises(HTTPException) as raised:
        require_approved_doctor(patient, db_session)
    assert raised.value.status_code == 403


def test_unapproved_doctor_cannot_use_approved_doctor_routes(db_session):
    doctor_user = _user(1, "doctor@example.test", role="doctor")
    db_session.add(doctor_user)
    db_session.flush()
    db_session.add(
        Doctor(
            user_id=doctor_user.id,
            full_name="Pending Doctor",
            specialty="General",
            license_number="PENDING-1",
            is_verified=False,
            status="pending",
        )
    )
    db_session.commit()

    with pytest.raises(HTTPException) as raised:
        require_approved_doctor(doctor_user, db_session)
    assert raised.value.status_code == 403


def test_consultation_denies_unrelated_patient_and_unassigned_doctor(db_session):
    patient_a = _user(1, "a@example.test")
    patient_b = _user(2, "b@example.test")
    doctor_a_user = _user(3, "doctor-a@example.test", role="doctor")
    doctor_b_user = _user(4, "doctor-b@example.test", role="doctor")
    db_session.add_all([patient_a, patient_b, doctor_a_user, doctor_b_user])
    db_session.flush()
    doctor_a = Doctor(
        user_id=doctor_a_user.id,
        full_name="Doctor A",
        specialty="General",
        license_number="DOC-A",
        is_verified=True,
        status="active",
    )
    doctor_b = Doctor(
        user_id=doctor_b_user.id,
        full_name="Doctor B",
        specialty="General",
        license_number="DOC-B",
        is_verified=True,
        status="active",
    )
    db_session.add_all([doctor_a, doctor_b])
    db_session.flush()
    db_session.add(
        Appointment(
            patient_id=patient_a.id,
            doctor_id=doctor_a.id,
            status="confirmed",
            payment_status="paid",
            start_time=datetime.utcnow(),
        )
    )
    db_session.commit()
    appointment = db_session.query(Appointment).one()

    for attacker in (patient_b, doctor_b_user):
        with pytest.raises(HTTPException) as raised:
            require_consultation_access(db_session, appointment.id, attacker)
        assert raised.value.status_code == 403


def test_protected_mutation_rejects_unauthenticated_request():
    app = FastAPI()
    app.include_router(notifications.router, prefix="/notifications")

    def override_db():
        yield None

    app.dependency_overrides[get_db] = override_db
    response = TestClient(app).patch("/notifications/123/read")
    assert response.status_code == 401


def test_admin_like_operation_rejects_normal_user():
    with pytest.raises(HTTPException) as raised:
        admin.get_current_admin(SimpleNamespace(role="patient"))
    assert raised.value.status_code == 403


def test_media_rejects_spoofed_extension_and_content_type():
    upload = UploadFile(
        io.BytesIO(b"<script>alert('x')</script>"),
        filename="scan.png",
        headers=Headers({"content-type": "image/png"}),
    )
    with pytest.raises(HTTPException) as raised:
        asyncio.run(read_validated_upload(upload))
    assert raised.value.status_code == 400


def test_profile_media_rejects_valid_pdf_content():
    upload = UploadFile(
        io.BytesIO(b"%PDF-1.7\nfixture"),
        filename="profile.pdf",
        headers=Headers({"content-type": "application/pdf"}),
    )
    with pytest.raises(HTTPException) as raised:
        asyncio.run(
            read_validated_upload(
                upload,
                allowed_types={"image/jpeg", "image/png", "image/webp"},
            )
        )
    assert raised.value.status_code == 400


def test_generic_media_route_has_no_client_controlled_folder_parameter():
    endpoint = inspect.unwrap(media.upload_file)
    assert "folder" not in inspect.signature(endpoint).parameters


def test_family_invite_is_one_time_and_cross_family_replay_is_rejected(db_session):
    primary = _user(
        1,
        "primary@example.test",
        plan="family",
        subscription_expiry=datetime.utcnow() + timedelta(days=20),
    )
    first_member = _user(2, "member-a@example.test")
    second_member = _user(3, "member-b@example.test")
    db_session.add_all([primary, first_member, second_member])
    db_session.commit()

    with patch.object(family, "_SECRET_KEY", "s" * 32):
        response = family.generate_invite_code(current_user=primary, db=db_session)
    with (
        patch.object(family, "_SECRET_KEY", "s" * 32),
        patch.object(family, "notify_user"),
    ):
        family.join_family(
            body=family.JoinRequest(invite_code=response.invite_code),
            current_user=first_member,
            db=db_session,
        )
        with pytest.raises(HTTPException) as raised:
            family.join_family(
                body=family.JoinRequest(invite_code=response.invite_code),
                current_user=second_member,
                db=db_session,
            )
    assert raised.value.status_code == 400


class _FakeWebSocket:
    def __init__(self, frames):
        self.frames = list(frames)
        self.close_code = None

    async def accept(self):
        return None

    async def receive_text(self):
        if self.frames:
            return self.frames.pop(0)
        raise WebSocketDisconnect()

    async def close(self, code=1000, reason=None):
        self.close_code = code

    async def send_text(self, value):
        return None


def test_websocket_rejects_claimed_user_identity_mismatch():
    websocket = _FakeWebSocket(['{"type":"auth","token":"signed-token"}'])
    user = SimpleNamespace(
        id=99,
        _auth_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    with (
        patch.object(chat_socket, "WsSession") as session_factory,
        patch.object(deps, "get_current_user", return_value=user),
        patch.object(chat_socket, "require_consultation_access") as authorize,
    ):
        session_factory.return_value.close.return_value = None
        asyncio.run(chat_socket.websocket_endpoint(websocket, 7, 5))

    assert websocket.close_code == 4403
    authorize.assert_not_called()


def test_websocket_rejects_unrelated_authenticated_participant():
    websocket = _FakeWebSocket(['{"type":"auth","token":"signed-token"}'])
    user = SimpleNamespace(
        id=5,
        _auth_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    with (
        patch.object(chat_socket, "WsSession") as session_factory,
        patch.object(deps, "get_current_user", return_value=user),
        patch.object(
            chat_socket,
            "require_consultation_access",
            side_effect=HTTPException(status_code=403, detail="forbidden"),
        ),
    ):
        session_factory.return_value.close.return_value = None
        asyncio.run(chat_socket.websocket_endpoint(websocket, 7, 5))

    assert websocket.close_code == 4403
