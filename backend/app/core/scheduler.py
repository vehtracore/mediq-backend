import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, update

from app.core.database import SessionLocal
from app.models.appointment import Appointment, DoctorSlot
from app.models.notification import Notification

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
