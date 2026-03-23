import hmac
import hashlib
import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from app.core.database import get_db
from app.models.user import User
from app.api import deps
from app.schemas.user import UserResponse

logger = logging.getLogger(__name__)

PAYSTACK_SECRET_KEY = os.environ.get("PAYSTACK_SECRET_KEY", "")
if not PAYSTACK_SECRET_KEY:
    logger.warning(
        "PAYSTACK_SECRET_KEY is not set. The /webhook endpoint will reject all requests."
    )

router = APIRouter()


@router.post("/upgrade", response_model=UserResponse)
def upgrade_to_premium(
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    current_user.plan = "premium"
    current_user.subscription_expiry = datetime.utcnow() + timedelta(days=30)

    db.commit()
    db.refresh(current_user)

    return current_user


@router.post("/webhook")
async def paystack_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Paystack webhook endpoint with HMAC SHA512 signature verification.
    Paystack signs every webhook payload with your secret key. We recompute
    the signature and compare it before processing any database changes.
    """

    # --- 1. Read the raw body bytes (must happen before any JSON parsing) ---
    body: bytes = await request.body()

    # --- 2. Extract the signature header ---
    signature = request.headers.get("x-paystack-signature", "")
    if not signature:
        logger.warning("Webhook received without x-paystack-signature header.")
        raise HTTPException(status_code=400, detail="Invalid signature")

    # --- 3. Compute the expected HMAC SHA512 hash ---
    expected_hash = hmac.new(
        PAYSTACK_SECRET_KEY.encode("utf-8"),
        msg=body,
        digestmod=hashlib.sha512,
    ).hexdigest()

    # --- 4. Timing-attack-safe comparison ---
    if not hmac.compare_digest(expected_hash, signature):
        logger.warning("Webhook signature mismatch – request rejected.")
        raise HTTPException(status_code=400, detail="Invalid signature")

    # --- 5. Signature valid – process the event ---
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event = payload.get("event", "")
    data = payload.get("data", {})

    if event == "subscription.create" or event == "charge.success":
        customer_email = data.get("customer", {}).get("email")
        if not customer_email:
            logger.error("Webhook payload missing customer email.")
            raise HTTPException(status_code=400, detail="Missing customer email")

        user = db.query(User).filter(User.email == customer_email).first()
        if not user:
            logger.error("No user found for email: %s", customer_email)
            raise HTTPException(status_code=404, detail="User not found")

        user.plan = "premium"
        user.subscription_expiry = datetime.utcnow() + timedelta(days=30)
        db.commit()

        logger.info("Upgraded user %s to premium via webhook.", customer_email)

    return {"status": "success"}