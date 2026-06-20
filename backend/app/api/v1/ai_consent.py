from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api import deps
from app.core.database import get_db
from app.models.user import User
from app.schemas.ai_consent import AIConsentStatusResponse


router = APIRouter()

# This identifies the disclosure accepted at the time consent is granted.
# Consent remains one-time and is not invalidated solely by changing this value.
AI_CONSENT_VERSION = "2026-06-19"


def require_active_ai_consent(user: User) -> None:
    """Block AI processing unless the user has active one-time consent."""
    if (
        user.ai_consent_granted_at is None
        or user.ai_consent_withdrawn_at is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="AI consent required before using the symptom checker.",
        )


def _consent_status(user: User) -> AIConsentStatusResponse:
    return AIConsentStatusResponse(
        consent_granted=(
            user.ai_consent_granted_at is not None
            and user.ai_consent_withdrawn_at is None
        ),
        consent_version=user.ai_consent_version,
        consent_granted_at=user.ai_consent_granted_at,
        consent_withdrawn_at=user.ai_consent_withdrawn_at,
    )


@router.post("/consent", response_model=AIConsentStatusResponse)
def grant_ai_consent(
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(get_db),
):
    # Keep an existing active consent unchanged so this endpoint is idempotent
    # and does not create a new consent event on every app session.
    if (
        current_user.ai_consent_granted_at is not None
        and current_user.ai_consent_withdrawn_at is None
    ):
        return _consent_status(current_user)

    current_user.ai_consent_granted_at = datetime.now(timezone.utc)
    current_user.ai_consent_version = AI_CONSENT_VERSION
    current_user.ai_consent_withdrawn_at = None
    db.commit()
    db.refresh(current_user)
    return _consent_status(current_user)


@router.get("/consent/status", response_model=AIConsentStatusResponse)
def get_ai_consent_status(
    current_user: User = Depends(deps.get_current_user),
):
    return _consent_status(current_user)


@router.post("/consent/withdraw", response_model=AIConsentStatusResponse)
def withdraw_ai_consent(
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(get_db),
):
    # Preserve the original withdrawal timestamp on repeated requests.
    if (
        current_user.ai_consent_granted_at is not None
        and current_user.ai_consent_withdrawn_at is None
    ):
        current_user.ai_consent_withdrawn_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(current_user)

    return _consent_status(current_user)
