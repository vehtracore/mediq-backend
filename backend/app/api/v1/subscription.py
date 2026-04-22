"""
Subscription Router
====================
Handles plan management endpoints.

NOTE: The Paystack webhook that previously lived here has been moved to
``app/api/v1/payments.py`` (POST /api/v1/payments/webhook) as part of the
production payment architecture refactor (2026-04-22).
"""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.api import deps
from app.schemas.user import UserResponse

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