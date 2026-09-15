from datetime import datetime

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.v1 import appointments as appointment_api
from app.models.appointment import Appointment, DoctorSlot
from app.models.doctor import Doctor
from app.models.review import Review
from app.models.user import User
from app.schemas.appointment import GeneralBookRequest


@pytest.fixture()
def queue_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        User.__table__,
        Doctor.__table__,
        DoctorSlot.__table__,
        Appointment.__table__,
        Review.__table__,
    ]
    for table in tables:
        table.create(engine, checkfirst=True)

    with Session(engine) as db:
        patient = User(
            id=1,
            first_name="Queue",
            last_name="Patient",
            email="queue-patient@example.test",
            role="patient",
            is_active=True,
        )
        doctor_user = User(
            id=2,
            first_name="Queue",
            last_name="Doctor",
            email="queue-doctor@example.test",
            role="doctor",
            is_active=True,
        )
        doctor = Doctor(
            id=10,
            user_id=doctor_user.id,
            full_name="Dr Queue",
            specialty="General Practice",
            status="active",
            is_verified=True,
            is_available=True,
        )
        db.add_all([patient, doctor_user, doctor])
        db.commit()
        yield db, patient, doctor_user, doctor


def _book(db: Session, patient: User):
    return appointment_api.book_general_consultation(
        GeneralBookRequest(notes="I need a doctor now."),
        db,
        patient,
    )


def test_general_queue_uses_one_row_through_completion_and_review(
    queue_session,
    monkeypatch,
) -> None:
    db, patient, doctor_user, doctor = queue_session
    first = _book(db, patient)
    replay = _book(db, patient)

    assert replay.id == first.id
    assert db.query(Appointment).count() == 1
    assert replay.paystack_reference == first.paystack_reference

    appointment = db.get(Appointment, first.id)
    appointment.payment_status = "paid"
    db.commit()
    monkeypatch.setattr(appointment_api, "_notify_patient", lambda *a, **k: None)
    claimed = appointment_api.claim_appointment(first.id, db, doctor_user)
    assert claimed.id == first.id
    assert claimed.status == "confirmed"

    appointment = db.get(Appointment, first.id)
    appointment.patient_joined_at = datetime.utcnow()
    appointment.doctor_joined_at = datetime.utcnow()
    appointment.consultation_started_at = datetime.utcnow()
    db.commit()
    monkeypatch.setattr(
        appointment_api,
        "complete_consultation",
        lambda _db, appt: setattr(appt, "status", "completed"),
    )
    completed = appointment_api.complete_appointment(
        first.id,
        db,
        doctor_user,
    )
    assert completed.status == "completed"

    db.add(
        Review(
            appointment_id=first.id,
            doctor_id=doctor.id,
            patient_id=patient.id,
            rating=5,
        )
    )
    db.commit()
    schedule = appointment_api.get_my_appointments(db, patient)

    logical_items = [item for item in schedule if item.id == first.id]
    assert len(logical_items) == 1
    assert logical_items[0].status == "completed"
    assert logical_items[0].has_review is True
    assert not any(item.status == "pending" for item in schedule)


@pytest.mark.parametrize(
    "terminal_status",
    ["cancelled", "queue_expired", "queue_patient_unavailable", "patient_no_show", "doctor_no_show", "both_no_show"],
)
def test_terminal_cancellation_and_no_show_states_allow_a_new_queue_request(
    queue_session,
    terminal_status,
) -> None:
    db, patient, _, _ = queue_session
    first = _book(db, patient)
    appointment = db.get(Appointment, first.id)
    appointment.status = terminal_status
    db.commit()

    replacement = _book(db, patient)

    assert replacement.id != first.id
    assert db.query(Appointment).count() == 2
    assert db.get(Appointment, first.id).status == terminal_status


def test_active_general_queue_unique_index_rejects_concurrent_duplicate(
    queue_session,
) -> None:
    db, patient, _, _ = queue_session
    _book(db, patient)
    db.add(
        Appointment(
            patient_id=patient.id,
            appointment_type="general_queue",
            status="pending",
            payment_status="unpaid",
            start_time=datetime.utcnow(),
        )
    )

    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    assert db.query(Appointment).count() == 1
