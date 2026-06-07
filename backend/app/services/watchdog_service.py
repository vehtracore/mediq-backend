"""
Payment Watchdog Service
========================
An async background sweep that runs every 5 minutes and finds
appointments whose payment is still pending long after creation.

For each stale record it calls the Paystack verification API and:

  • status == "success"   → marks the appointment paid/confirmed
                             (reuses _apply_db_update from payments.py)
  • status == "failed"
    or "abandoned"        → marks the appointment payment_status = "failed"
                             and status = "cancelled" so it leaves the queue
  • anything else         → leaves the record untouched for the next sweep

The job opens its own SQLAlchemy session (SessionLocal) because it runs
outside of a FastAPI request context and therefore has no Depends(get_db).

Design decisions
----------------
- Uses httpx.AsyncClient for non-blocking Paystack calls.
- Processes records sequentially to stay well within rate-limit budgets.
- Never raises — any unhandled exception is logged so APScheduler
  doesn't silently swallow it.
"""

import logging
import os
from datetime import datetime, timedelta

import httpx

from app.core.database import SessionLocal
from app.models.appointment import Appointment

logger = logging.getLogger(__name__)

PAYSTACK_SECRET_KEY: str = os.environ.get("PAYSTACK_SECRET_KEY", "")
PAYSTACK_VERIFY_URL = "https://api.paystack.co/transaction/verify"

# Appointments younger than this are still "in-flight" (user may be on the
# checkout sheet), so we leave them alone.
_STALE_AFTER_MINUTES: int = 5


async def sweep_pending_transactions() -> None:
    """
    Async watchdog job — safe to schedule with AsyncIOScheduler.

    Queries for unpaid appointments older than _STALE_AFTER_MINUTES,
    verifies each one with Paystack, and updates the database accordingly.
    """
    if not PAYSTACK_SECRET_KEY:
        logger.warning(
            "[WATCHDOG] ⚠️  PAYSTACK_SECRET_KEY not set — sweep skipped."
        )
        return

    db = SessionLocal()
    try:
        cutoff: datetime = datetime.utcnow() - timedelta(minutes=_STALE_AFTER_MINUTES)

        # ── Query: unpaid appointments older than the cutoff ──────────────────
        stale: list[Appointment] = (
            db.query(Appointment)
            .filter(
                Appointment.payment_status == "unpaid",
                Appointment.status == "pending",
                Appointment.start_time <= cutoff,
            )
            .all()
        )

        if not stale:
            logger.debug("[WATCHDOG] No stale pending appointments found.")
            return

        logger.info("[WATCHDOG] 🔍 Found %d stale pending appointment(s).", len(stale))

        headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"}

        async with httpx.AsyncClient(timeout=15.0) as client:
            for appt in stale:
                # Each appointment stores the Paystack reference embedded
                # during checkout.  Skip rows that predate this field.
                reference: str = getattr(appt, "paystack_reference", None) or ""
                if not reference:
                    logger.debug(
                        "[WATCHDOG] Appointment id=%s has no reference — skipping.",
                        appt.id,
                    )
                    continue

                await _verify_and_update(client, appt, reference, headers, db)

    except Exception as exc:
        logger.exception("[WATCHDOG] 🚨 Unexpected error during sweep: %s", exc)
    finally:
        db.close()


async def _verify_and_update(
    client: httpx.AsyncClient,
    appt: Appointment,
    reference: str,
    headers: dict,
    db,
) -> None:
    """Verify a single appointment reference with Paystack and update the DB."""
    try:
        resp = await client.get(f"{PAYSTACK_VERIFY_URL}/{reference}", headers=headers)
        data: dict = resp.json()
    except httpx.RequestError as exc:
        logger.error(
            "[WATCHDOG] HTTP error verifying reference='%s': %s", reference, exc,
            exc_info=True,
        )
        return

    if not data.get("status"):
        logger.warning(
            "[WATCHDOG] Paystack error for reference='%s': %s",
            reference,
            data.get("message"),
        )
        return

    tx_data: dict = data.get("data") or {}
    paystack_status: str = tx_data.get("status", "")

    # ── Successful payment ─────────────────────────────────────────────────────
    if paystack_status == "success":
        logger.info(
            "[WATCHDOG] ✅ Payment confirmed — appt_id=%s | reference='%s'",
            appt.id,
            reference,
        )
        try:
            # Import here to avoid circular dependency at module load time.
            from app.api.v1.payments import _parse_reference, _apply_db_update

            transaction_type, ref_appointment_id, ref_user_id = _parse_reference(
                reference
            )
            _apply_db_update(
                transaction_type=transaction_type,
                ref_appointment_id=ref_appointment_id,
                ref_user_id=ref_user_id,
                reference=reference,
                db=db,
                # No BackgroundTasks context available in a scheduler job.
                # Emails are handled by the webhook / verify endpoint.
                background_tasks=None,
            )
        except Exception as exc:
            logger.error(
                "[WATCHDOG] DB update failed for reference='%s': %s", reference, exc,
                exc_info=True,
            )

    # ── Failed or abandoned payment ────────────────────────────────────────────
    elif paystack_status in ("failed", "abandoned"):
        logger.info(
            "[WATCHDOG] ❌ Payment %s — marking appt_id=%s cancelled.",
            paystack_status,
            appt.id,
        )
        try:
            appt.payment_status = "failed"
            appt.status = "cancelled"
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.error(
                "[WATCHDOG] Failed to cancel appt_id=%s: %s", appt.id, exc,
                exc_info=True,
            )

    # ── Still pending / processing ─────────────────────────────────────────────
    else:
        logger.debug(
            "[WATCHDOG] Reference='%s' still has status='%s' — leaving for next sweep.",
            reference,
            paystack_status,
        )
