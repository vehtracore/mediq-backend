import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, update
from sqlalchemy.orm import joinedload

from app.core.database import SessionLocal
from app.models.appointment import (
    Appointment,
    DoctorSlot,
    attendance_deadline_utc,
    consultation_started_utc,
)
from app.models.notification import Notification
from app.services.consultation_pricing import (
    DEFAULT_CONSULTATION_DURATION_MINUTES,
    CONSULTATION_MESSAGE_GRACE_MINUTES,
)
from app.services.consultation_payout_service import (
    ensure_general_queue_payout,
    process_approved_general_queue_payouts,
)
from app.services.consultation_refund_service import (
    REFUND_STATUS_AWAITING_ADMIN,
    process_approved_consultation_refunds,
)

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
        Appointments with status == 'active' or 'confirmed' whose start_time is
        older than 24 hours are marked 'completed'. This prevents consultations
        from hanging open indefinitely when a doctor forgets to close them.

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
            .where(Appointment.status.in_(("active", "confirmed")))
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


async def complete_expired_consultations() -> None:
    """Auto-complete sessions after video time plus the message grace period."""
    now = datetime.now(timezone.utc)
    close_after = timedelta(
        minutes=(
            DEFAULT_CONSULTATION_DURATION_MINUTES
            + CONSULTATION_MESSAGE_GRACE_MINUTES
        )
    )

    db = SessionLocal()
    try:
        appointments = (
            db.query(Appointment)
            .options(joinedload(Appointment.slot))
            .filter(Appointment.status.in_(("active", "confirmed")))
            .all()
        )
        completed = 0
        for appointment in appointments:
            start = consultation_started_utc(appointment)
            if start is not None and now >= start + close_after:
                appointment.status = "completed"
                ensure_general_queue_payout(db, appointment)
                completed += 1

        db.commit()
        if completed:
            logger.info(
                "[APPT SWEEP] Auto-completed %d consultation(s) after grace period.",
                completed,
            )
    except Exception as exc:
        db.rollback()
        logger.exception(
            "[APPT SWEEP] Error completing expired consultations: %s",
            exc,
        )
    finally:
        db.close()


async def mark_consultation_no_shows() -> None:
    """Classify confirmed appointments where the second party never arrived."""
    now = datetime.now(timezone.utc)
    now_naive = now.replace(tzinfo=None)

    db = SessionLocal()
    try:
        appointments = (
            db.query(Appointment)
            .options(joinedload(Appointment.slot))
            .filter(
                Appointment.status == "confirmed",
                Appointment.payment_status == "paid",
                Appointment.consultation_started_at.is_(None),
            )
            .all()
        )
        counts = {
            "patient_no_show": 0,
            "doctor_no_show": 0,
            "both_no_show": 0,
        }
        for appointment in appointments:
            deadline = attendance_deadline_utc(appointment)
            if deadline is None or now < deadline:
                continue

            patient_joined = appointment.patient_joined_at is not None
            doctor_joined = appointment.doctor_joined_at is not None
            if doctor_joined and not patient_joined:
                appointment.status = "patient_no_show"
            elif patient_joined and not doctor_joined:
                appointment.status = "doctor_no_show"
                appointment.refund_status = REFUND_STATUS_AWAITING_ADMIN
            else:
                appointment.status = "both_no_show"
                appointment.refund_status = REFUND_STATUS_AWAITING_ADMIN

            appointment.no_show_marked_at = now_naive
            ensure_general_queue_payout(db, appointment)
            counts[appointment.status] += 1

        db.commit()
        if any(counts.values()):
            logger.info(
                "[NO SHOW] patient=%d doctor=%d both=%d",
                counts["patient_no_show"],
                counts["doctor_no_show"],
                counts["both_no_show"],
            )
    except Exception as exc:
        db.rollback()
        logger.exception("[NO SHOW] Classification failed: %s", exc)
    finally:
        db.close()


async def cleanup_old_notifications() -> None:
    """Nightly bulk-delete notifications older than the 90-day retention window."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)

    db = SessionLocal()
    try:
        result = db.execute(
            delete(Notification).where(Notification.created_at < cutoff)
        )
        db.commit()
        logger.info(
            "[NOTIFICATION CLEANUP] Deleted %d notification(s) older than 90 days.",
            result.rowcount,
        )
    except Exception as exc:
        db.rollback()
        logger.exception("[NOTIFICATION CLEANUP] Error during retention sweep: %s", exc)
    finally:
        db.close()


async def send_appointment_reminders() -> None:
    """
    Deprecated by the major-events-only notification policy.

    Daily reminders are intentionally disabled to prevent notification spam.
    """
    logger.info("[REMINDER] Appointment reminder pushes are disabled.")
