import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, update

from app.core.database import SessionLocal
from app.models.appointment import Appointment, DoctorSlot

logger = logging.getLogger("uvicorn.error")


async def cleanup_expired_slots() -> None:
    """
    Cron job — runs nightly at 00:00 UTC.

    Bulk-deletes every row in ``doctor_slots`` whose ``start_time`` is in the
    past and that has never been booked (``is_booked == False``).  Booked slots
    are intentionally left in place so that existing Appointment foreign-key
    references remain valid.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)  # DB stores naive UTC

    db = SessionLocal()
    try:
        stmt = (
            delete(DoctorSlot)
            .where(DoctorSlot.start_time < now)
            .where(DoctorSlot.is_booked == False)  # noqa: E712
        )
        result = db.execute(stmt)
        db.commit()

        deleted = result.rowcount
        logger.info(
            "[SLOT CLEANUP] Nightly sweep complete — %d expired unbooked slot(s) deleted.",
            deleted,
        )
    except Exception as exc:
        db.rollback()
        logger.exception("[SLOT CLEANUP] Error during nightly sweep: %s", exc)
    finally:
        db.close()


async def sweep_stale_appointments() -> None:
    """
    Hourly cron job — resolves two categories of stale appointments.

    Sweep 1 (Liability — auto-close):
        Appointments with status == 'active' whose start_time is older than
        24 hours are marked 'completed'.  This prevents consultations from
        hanging open indefinitely when a doctor forgets to close them.

    Sweep 2 (Limbo — unclaimed cancellation):
        Appointments with status == 'pending' whose start_time is older than
        24 hours are marked 'cancelled'.  These are bookings that were never
        accepted by a doctor and have now expired.

    Both queries operate on naive UTC timestamps to match the column storage
    convention used throughout the project (datetime.utcnow, no tzinfo).
    """
    # DB columns are stored as naive UTC — strip tzinfo before comparing.
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)

    db = SessionLocal()
    try:
        # -- Sweep 1: active → completed (24-hour auto-close) -----------------
        stmt_active = (
            update(Appointment)
            .where(Appointment.status == "active")
            .where(Appointment.start_time < cutoff)
            .values(status="completed")
        )
        result_active = db.execute(stmt_active)

        # -- Sweep 2: pending → cancelled (unclaimed / expired) ---------------
        stmt_pending = (
            update(Appointment)
            .where(Appointment.status == "pending")
            .where(Appointment.start_time < cutoff)
            .values(status="cancelled")
        )
        result_pending = db.execute(stmt_pending)

        db.commit()

        closed = result_active.rowcount
        cancelled = result_pending.rowcount
        logger.info(
            "[APPT SWEEP] Cron Sweep complete — "
            "Closed %d active appointment(s) | "
            "Cancelled %d pending appointment(s).",
            closed,
            cancelled,
        )
    except Exception as exc:
        db.rollback()
        logger.exception("[APPT SWEEP] Error during stale-appointment sweep: %s", exc)
    finally:
        db.close()


async def send_appointment_reminders() -> None:
    """
    Daily cron job — runs at 07:00 UTC.

    Queries every **confirmed** appointment whose ``start_time`` falls within
    the current UTC calendar day and fires an FCM push notification to:
      • the patient  — so they remember to join their session.
      • the doctor   — so they are aware of their schedule for the day.

    Design notes
    ────────────
    • DB timestamps are stored as *naive* UTC datetimes, so we compare against
      naive UTC boundaries.
    • Each appointment's notification is wrapped in its own try/except so a
      single FCM failure never aborts the rest of the batch.
    • ``logger.error`` is used for FCM failures so Sentry's LoggingIntegration
      (wired in main.py) automatically creates a Sentry issue.
    • Doctor lookup is done via the Doctor → User join so we only send a push
      when the doctor has a registered FCM token.
    """
    from app.models.user import User
    from app.models.doctor import Doctor
    from app.core.notifications import dispatch_push

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    day_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    db = SessionLocal()
    try:
        todays_appts = (
            db.query(Appointment)
            .filter(
                Appointment.status == "confirmed",
                Appointment.start_time >= day_start,
                Appointment.start_time < day_end,
            )
            .all()
        )

        logger.info(
            "[REMINDER] Daily sweep — %d confirmed appointment(s) today (%s).",
            len(todays_appts),
            day_start.strftime("%Y-%m-%d"),
        )

        for appt in todays_appts:
            # ── Resolve start time string ─────────────────────────────────────
            time_str = (
                appt.start_time.strftime("%H:%M UTC")
                if appt.start_time
                else "scheduled time"
            )

            # ── Patient reminder ──────────────────────────────────────────────
            try:
                patient: User | None = (
                    db.query(User).filter(User.id == appt.patient_id).first()
                    if appt.patient_id
                    else None
                )
                if patient and patient.fcm_token:
                    dispatch_push(
                        token=patient.fcm_token,
                        title="📅 Appointment Reminder",
                        body=f"You have a consultation today at {time_str}. Open the app to join.",
                        data={
                            "type": "appointment_reminder",
                            "appointment_id": str(appt.id),
                        },
                        event_label="REMINDER/PATIENT",
                    )
            except Exception as exc:
                logger.error(
                    "[REMINDER] Patient FCM failed — appt_id=%s patient_id=%s: %s",
                    appt.id,
                    appt.patient_id,
                    exc,
                    exc_info=True,
                )

            # ── Doctor reminder ───────────────────────────────────────────────
            try:
                doctor: Doctor | None = (
                    db.query(Doctor).filter(Doctor.id == appt.doctor_id).first()
                    if appt.doctor_id
                    else None
                )
                if doctor:
                    doctor_user: User | None = (
                        db.query(User).filter(User.id == doctor.user_id).first()
                    )
                    if doctor_user and doctor_user.fcm_token:
                        # Resolve patient name for the doctor's notification
                        patient_name = "a patient"
                        if appt.patient_id:
                            p = db.query(User).filter(User.id == appt.patient_id).first()
                            if p:
                                patient_name = f"{p.first_name} {p.last_name}".strip() or "a patient"

                        dispatch_push(
                            token=doctor_user.fcm_token,
                            title="🩺 Consultation Today",
                            body=f"You have a session with {patient_name} at {time_str}.",
                            data={
                                "type": "appointment_reminder",
                                "appointment_id": str(appt.id),
                            },
                            event_label="REMINDER/DOCTOR",
                        )
            except Exception as exc:
                logger.error(
                    "[REMINDER] Doctor FCM failed — appt_id=%s doctor_id=%s: %s",
                    appt.id,
                    appt.doctor_id,
                    exc,
                    exc_info=True,
                )

        logger.info("[REMINDER] Daily reminder sweep complete.")

    except Exception as exc:
        logger.exception("[REMINDER] Unhandled error in send_appointment_reminders: %s", exc)
    finally:
        db.close()
