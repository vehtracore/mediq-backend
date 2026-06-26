import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, update
from sqlalchemy.orm import joinedload

from app.core.database import SessionLocal
from app.models.appointment import (
    APPOINTMENT_TYPE_GENERAL_QUEUE,
    Appointment,
    DoctorSlot,
    attendance_deadline_utc,
    consultation_started_utc,
    resolve_appointment_type,
)
from app.models.notification import Notification
from app.services.consultation_pricing import (
    DEFAULT_CONSULTATION_DURATION_MINUTES,
    CONSULTATION_MESSAGE_GRACE_MINUTES,
)
from app.services.consultation_completion import complete_consultation
from app.services.consultation_payout_service import (
    ensure_consultation_payout,
    process_approved_consultation_payouts,
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
    """Cancel stale pending appointments that never moved into a paid/active flow.

    Confirmed consultations are intentionally not completed here. Started
    consultations are closed by access-control timing first, then completed by
    the nightly consultation completion sweep if the doctor forgets to mark
    complete.
    """
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now_naive - timedelta(hours=24)

    db = SessionLocal()
    try:
        stmt_paid_queue = (
            update(Appointment)
            .where(Appointment.appointment_type == APPOINTMENT_TYPE_GENERAL_QUEUE)
            .where(Appointment.status == "pending")
            .where(Appointment.payment_status == "paid")
            .where(Appointment.start_time < cutoff)
            .values(
                status="queue_expired",
                refund_status=REFUND_STATUS_AWAITING_ADMIN,
                no_show_marked_at=now_naive,
            )
        )
        result_paid_queue = db.execute(stmt_paid_queue)

        stmt_pending = (
            update(Appointment)
            .where(Appointment.status == "pending")
            .where(Appointment.start_time < cutoff)
            .values(status="cancelled")
        )
        result_pending = db.execute(stmt_pending)

        db.commit()

        queue_expired = result_paid_queue.rowcount
        cancelled = result_pending.rowcount
        if queue_expired or cancelled:
            logger.info(
                "[APPT SWEEP] Queue refund review=%d | Cancelled stale pending=%d.",
                queue_expired,
                cancelled,
            )
    except Exception as exc:
        db.rollback()
        logger.exception("[APPT SWEEP] Error during stale-appointment sweep: %s", exc)
    finally:
        db.close()


async def complete_expired_consultations() -> None:
    """Nightly cleanup for started consultations whose grace period has ended.

    The consultation room closes immediately through access-control timing, but
    status remains confirmed so the doctor can still write prescription, referral,
    notes, and manually mark complete. This job completes forgotten wrap-ups at
    end of day using the same vault/payout side effects as manual completion.
    """
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
                complete_consultation(db, appointment)
                completed += 1

        db.commit()
        if completed:
            logger.info(
                "[APPT SWEEP] Auto-completed %d consultation(s) in nightly wrap-up.",
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
            "queue_patient_unavailable": 0,
            "returned_to_queue": 0,
        }
        for appointment in appointments:
            deadline = attendance_deadline_utc(appointment)
            if deadline is None or now < deadline:
                continue

            patient_joined = appointment.patient_joined_at is not None
            doctor_joined = appointment.doctor_joined_at is not None
            appointment_type = resolve_appointment_type(appointment)

            if (
                appointment_type == APPOINTMENT_TYPE_GENERAL_QUEUE
                and patient_joined
                and not doctor_joined
            ):
                missed_doctor_id = appointment.doctor_id
                appointment.doctor_id = None
                appointment.status = "pending"
                appointment.start_time = now_naive
                appointment.patient_joined_at = None
                appointment.doctor_joined_at = None
                appointment.consultation_started_at = None
                appointment.no_show_marked_at = None
                appointment.refund_status = None
                counts["returned_to_queue"] += 1
                logger.warning(
                    "[GENERAL QUEUE] Returned appt_id=%s to paid queue after doctor_no_show doctor_id=%s.",
                    appointment.id,
                    missed_doctor_id,
                )
                continue

            if doctor_joined and not patient_joined:
                if appointment_type == APPOINTMENT_TYPE_GENERAL_QUEUE:
                    appointment.status = "queue_patient_unavailable"
                    appointment.refund_status = REFUND_STATUS_AWAITING_ADMIN
                else:
                    appointment.status = "patient_no_show"
            elif patient_joined and not doctor_joined:
                appointment.status = "doctor_no_show"
                appointment.refund_status = REFUND_STATUS_AWAITING_ADMIN
            else:
                appointment.status = "both_no_show"
                appointment.refund_status = REFUND_STATUS_AWAITING_ADMIN

            appointment.no_show_marked_at = now_naive
            ensure_consultation_payout(db, appointment)
            counts[appointment.status] += 1

        db.commit()
        if any(counts.values()):
            logger.info(
                "[NO SHOW] patient=%d doctor=%d both=%d queue_patient_unavailable=%d returned_queue=%d",
                counts["patient_no_show"],
                counts["doctor_no_show"],
                counts["both_no_show"],
                counts["queue_patient_unavailable"],
                counts["returned_to_queue"],
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
