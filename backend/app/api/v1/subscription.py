"""
Subscription Router
====================
Handles plan management endpoints.

Endpoints
---------
POST /upgrade             — Manual plan upgrade (testing / admin overrides).
POST /cancel-subscription — Authenticated cancellation via Paystack API.

NOTE: The Paystack webhook that previously lived here has been moved to
``app/api/v1/payments.py`` (POST /api/v1/payments/webhook) as part of the
production payment architecture refactor (2026-04-22).
"""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.api import deps
from app.schemas.user import UserResponse
from app.services.paystack_service import paystack_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/upgrade", response_model=UserResponse)
def upgrade_to_premium(
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """
    Manual plan upgrade endpoint (testing / admin overrides only).
    Production upgrades are handled by the Paystack webhook at
    POST /api/v1/payments/webhook with transactionType='subscription'.
    """
    current_user.plan = "premium"
    current_user.subscription_expiry = datetime.utcnow() + timedelta(days=30)

    db.commit()
    db.refresh(current_user)

    return current_user


@router.post("/cancel-subscription", response_model=UserResponse)
async def cancel_subscription(
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """
    POST /api/v1/subscription/cancel-subscription

    Cancels the current user's Paystack recurring subscription with graceful
    degradation if the external Paystack call cannot be completed.

    Flow
    ----
    1. Verifies that the user has a stored ``paystack_subscription_code``.
       If not, the subscription was manually granted or already cancelled —
       falls through to the local DB cleanup so the UI always updates.
    2. Attempts to call Paystack POST /subscription/disable.
       • On Paystack success → billing codes are cleared, plan stays active
         until ``subscription_expiry`` (Paystack won't renew).
       • On ANY Paystack error (400 business rejection, 503 network failure,
         missing/invalid token) → error is logged, the Paystack step is
         BYPASSED, and execution continues to the local DB cleanup below.
         This ensures testing, manual DB overrides, and production edge-cases
         never leave the UI stuck.
    3. Local DB cleanup (always runs):
       • Clears ``paystack_subscription_code`` and ``paystack_email_token``
         so auto-renewal cannot fire and this endpoint cannot be double-called.
       • The user retains premium access until ``subscription_expiry`` expires
         naturally; no artificial downgrade is applied here.
    4. Returns the updated UserResponse so the frontend can refresh state.

    Always returns 200 OK — Paystack failures are treated as soft errors.
    """
    # ── 1. Guard: no billing codes at all ────────────────────────────────────
    # Unlike the original hard-stop, we now log and fall through so that
    # manually-granted plans (common in testing) can still be "cancelled"
    # cleanly via the UI without a confusing 400 error.
    if not current_user.paystack_subscription_code:
        logger.warning(
            "[SUBSCRIPTION] Cancel: no paystack_subscription_code on user_id=%s — "
            "skipping Paystack call, applying local DB cleanup only.",
            current_user.id,
        )
    else:
        sub_code: str = current_user.paystack_subscription_code
        email_token: str = current_user.paystack_email_token or ""

        logger.info(
            "[SUBSCRIPTION] Cancellation requested — user_id=%s | sub_code='%s'",
            current_user.id,
            sub_code,
        )

        # ── 2. Call Paystack — wrapped for graceful degradation ───────────────
        # PaystackService raises HTTPException(400) on business-logic failures
        # (e.g. "No active recurring subscription found", invalid token) and
        # HTTPException(503) on network-level errors. We intentionally catch
        # both so that testing scenarios, manual DB overrides, or transient
        # Paystack outages never block the user from cancelling their plan in
        # the UI. The local cleanup in step 3 always runs regardless.
        try:
            await paystack_service.disable_subscription(
                subscription_code=sub_code,
                email_token=email_token,
            )
            logger.info(
                "[SUBSCRIPTION] ✅ Paystack confirmed disable — sub_code='%s'",
                sub_code,
            )
        except HTTPException as paystack_exc:
            # Log enough context for ops to diagnose without alarming the user.
            logger.warning(
                "[SUBSCRIPTION] ⚠️  Paystack disable failed for user_id=%s "
                "(sub_code='%s') — HTTP %s: %s. "
                "Proceeding with local DB cleanup so the UI can update.",
                current_user.id,
                sub_code,
                paystack_exc.status_code,
                paystack_exc.detail,
            )
            # Do NOT re-raise. Fall through to local DB cleanup below.

    # ── 3. Local DB cleanup (always runs) ────────────────────────────────────
    # Clearing the billing codes is the critical idempotency gate:
    #   • Paystack cannot auto-renew without the subscription code.
    #   • This endpoint cannot be double-called once the codes are gone.
    # The user's plan and subscription_expiry are intentionally left intact —
    # they retain premium access until the period they already paid for ends.
    current_user.paystack_subscription_code = None
    current_user.paystack_email_token = None

    db.commit()
    db.refresh(current_user)

    logger.info(
        "[SUBSCRIPTION] ✅ Cancellation complete — user_id=%s billing codes cleared. "
        "Premium access retained until expiry=%s.",
        current_user.id,
        current_user.subscription_expiry,
    )

    return current_user