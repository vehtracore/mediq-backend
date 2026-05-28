import logging
from datetime import datetime, timezone

from sqlalchemy import delete

from app.core.database import SessionLocal
from app.models.appointment import DoctorSlot

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
