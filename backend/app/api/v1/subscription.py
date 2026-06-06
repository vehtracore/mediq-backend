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

    Cancels the current user's active Paystack recurring subscription.

    Flow
    ----
    1. Verifies that the user has a stored ``paystack_subscription_code``.
       If not, the subscription was either manually granted or has already
       been cancelled — returns HTTP 400 with a clear message.
    2. Calls Paystack POST /subscription/disable using both the
       ``subscription_code`` and ``email_token`` stored on the user row.
    3. On Paystack success, reverts the user's plan to ``"free"``, clears
       ``subscription_expiry``, and nullifies both stored billing codes so
       this endpoint cannot be double-called.
    4. Returns the updated UserResponse so the frontend can refresh state.

    Error responses
    ---------------
    400  No active subscription found.
    400  Paystack rejected the cancellation (propagated from PaystackService).
    503  Could not reach Paystack (propagated from PaystackService).
    """
    # ── 1. Guard: subscription code must exist ────────────────────────────────
    if not current_user.paystack_subscription_code:
        logger.warning(
            "[SUBSCRIPTION] Cancel attempted but no subscription_code on user_id=%s",
            current_user.id,
        )
        raise HTTPException(
            status_code=400,
            detail=(
                "No active recurring subscription found on this account. "
                "If you believe this is an error, please contact support."
            ),
        )

    sub_code: str = current_user.paystack_subscription_code
    email_token: str = current_user.paystack_email_token or ""

    logger.info(
        "[SUBSCRIPTION] Cancellation requested — user_id=%s | sub_code='%s'",
        current_user.id,
        sub_code,
    )

    # ── 2. Call Paystack to disable the subscription ──────────────────────────
    # PaystackService raises HTTPException on failure; let it propagate.
    await paystack_service.disable_subscription(
        subscription_code=sub_code,
        email_token=email_token,
    )

    # ── 3. Clear billing codes only — do NOT touch plan or subscription_expiry ──
    # The user retains premium access until their paid period expires naturally.
    # Clearing the codes prevents Paystack from auto-renewing on the next cycle
    # and prevents this endpoint from being double-called.
    current_user.paystack_subscription_code = None
    current_user.paystack_email_token = None

    db.commit()
    db.refresh(current_user)

    logger.info(
        "[SUBSCRIPTION] ✅ Subscription disabled — user_id=%s billing codes cleared. "
        "Premium access retained until expiry=%s",
        current_user.id,
        current_user.subscription_expiry,
    )

    return current_user