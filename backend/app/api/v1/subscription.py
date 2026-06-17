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


def _is_subscription_unexpired(expiry: datetime | None) -> bool:
    if expiry is None:
        return False

    now = datetime.now(expiry.tzinfo) if expiry.tzinfo else datetime.utcnow()
    return expiry > now


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
    current_user.auto_renew = False

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

    Cancels the current user's Paystack recurring subscription while keeping
    local renewal state aligned with Paystack.

    Flow
    ----
    1. Verifies that the user has a stored ``paystack_subscription_code``.
       If not, the subscription was manually granted or already cancelled —
       falls through to the local DB cleanup so the UI always updates.
    2. Attempts to call Paystack POST /subscription/disable.
       • On Paystack success → auto_renew is set false, plan stays active
         until ``subscription_expiry`` (Paystack won't renew).
       • On Paystack error → the error is returned and local auto_renew state
         is left unchanged so the UI never lies about billing status.
    3. Local DB state update after successful Paystack disable:
       • Keeps ``paystack_subscription_code`` and ``paystack_email_token`` so
         an unexpired cancellation can be restored without checkout.
       • Marks ``auto_renew`` false locally.
       • The user retains premium access until ``subscription_expiry`` expires
         naturally; no artificial downgrade is applied here.
    4. Returns the updated UserResponse so the frontend can refresh state.

    Returns 200 only when Paystack cancellation succeeds. If billing
    identifiers are missing, returns 400 without mutating local renewal state.
    """
    # ── 1. Guard: recurring billing identifiers are required ─────────────────
    # Without these identifiers we cannot disable Paystack recurring billing,
    # and pretending the cancellation succeeded creates a broken "cancelled but
    # unrestorable" state in the UI.
    if not current_user.paystack_subscription_code:
        logger.warning(
            "[SUBSCRIPTION] Cancel blocked: no paystack_subscription_code on user_id=%s.",
            current_user.id,
        )
        raise HTTPException(
            status_code=400,
            detail=(
                "No saved billing subscription was found for this account. "
                "Please renew from checkout or contact support."
            ),
        )

    if not current_user.paystack_email_token:
        logger.warning(
            "[SUBSCRIPTION] Cancel blocked: no paystack_email_token on user_id=%s.",
            current_user.id,
        )
        raise HTTPException(
            status_code=400,
            detail=(
                "Subscription cancellation token is missing. "
                "Please contact support."
            ),
        )

    sub_code: str = current_user.paystack_subscription_code
    email_token: str = current_user.paystack_email_token

    logger.info(
        "[SUBSCRIPTION] Cancellation requested — user_id=%s | sub_code='%s'",
        current_user.id,
        sub_code,
    )

    # ── 2. Call Paystack ─────────────────────────────────────────────────
    # PaystackService raises HTTPException(400) on business-logic failures
    # (e.g. "No active recurring subscription found", invalid token) and
    # HTTPException(503) on network-level errors. Local auto_renew is only
    # changed after Paystack confirms disable, keeping billing state honest.
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
            "(sub_code='%s') — HTTP %s: %s. Local auto_renew unchanged.",
            current_user.id,
            sub_code,
            paystack_exc.status_code,
            paystack_exc.detail,
        )
        raise

    # ── 3. Local DB state (always runs) ───────────────────────────────────────
    # Keep the Paystack subscription identifiers so an unexpired cancellation
    # can be restored with /subscription/enable. The local auto_renew flag is
    # the source of truth for whether recurring billing is currently active.
    current_user.auto_renew = False

    db.commit()
    db.refresh(current_user)

    logger.info(
        "[SUBSCRIPTION] ✅ Cancellation complete — user_id=%s auto_renew disabled. "
        "Premium access retained until expiry=%s.",
        current_user.id,
        current_user.subscription_expiry,
    )

    return current_user


@router.post("/restore", response_model=UserResponse)
async def restore_subscription(
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """
    POST /api/v1/subscription/restore

    Re-enables auto-renew for an unexpired, previously cancelled Paystack
    subscription without forcing the user through checkout again.
    """
    if not current_user.paystack_subscription_code:
        raise HTTPException(
            status_code=400,
            detail="No saved subscription found to restore.",
        )

    if not current_user.paystack_email_token:
        raise HTTPException(
            status_code=400,
            detail="Subscription restore token is missing. Please renew from checkout.",
        )

    if not _is_subscription_unexpired(current_user.subscription_expiry):
        raise HTTPException(
            status_code=400,
            detail="This subscription has expired. Please renew from checkout.",
        )

    await paystack_service.enable_subscription(
        subscription_code=current_user.paystack_subscription_code,
        email_token=current_user.paystack_email_token,
    )

    current_user.auto_renew = True
    db.commit()
    db.refresh(current_user)

    logger.info(
        "[SUBSCRIPTION] ✅ Restore complete — user_id=%s auto_renew enabled.",
        current_user.id,
    )

    return current_user
