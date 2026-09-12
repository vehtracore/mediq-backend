"""Authenticated, durable customer-support submission endpoint."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.api import deps
from app.core.database import get_db
from app.core.limiter import limiter
from app.models.support_message import SupportMessage
from app.models.user import User
from app.services import support_email_service

logger = logging.getLogger(__name__)

router = APIRouter()

_RETRYABLE_DETAIL = (
    "We couldn't send your message right now. Your message was retained but "
    "hasn't been marked as sent. Please try again."
)


class SupportMessageRequest(BaseModel):
    """Body for POST /api/v1/support/contact."""

    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    subject: str = Field(..., min_length=1, max_length=120)
    message: str = Field(..., min_length=1, max_length=5000)

    @field_validator("subject", "message", mode="before")
    @classmethod
    def trim_content(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class SupportMessageResponse(BaseModel):
    request_id: UUID
    status: str


def _resolve_submission(
    db: Session,
    *,
    payload: SupportMessageRequest,
    user_id: int,
) -> SupportMessage:
    existing = (
        db.query(SupportMessage)
        .filter(SupportMessage.request_id == payload.request_id)
        .first()
    )
    if existing is not None:
        if (
            existing.user_id != user_id
            or existing.subject != payload.subject
            or existing.message != payload.message
        ):
            raise HTTPException(
                status_code=409,
                detail="This support request identifier is already in use.",
            )
        return existing

    submission = SupportMessage(
        request_id=payload.request_id,
        user_id=user_id,
        subject=payload.subject,
        message=payload.message,
        email_status="pending",
    )
    db.add(submission)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(SupportMessage)
            .filter(SupportMessage.request_id == payload.request_id)
            .first()
        )
        if (
            existing is None
            or existing.user_id != user_id
            or existing.subject != payload.subject
            or existing.message != payload.message
        ):
            raise HTTPException(
                status_code=409,
                detail="This support request identifier is already in use.",
            )
        return existing

    db.refresh(submission)
    logger.info(
        "[SUPPORT] Durable submission created | request_id=%s | user_id=%s",
        submission.request_id,
        user_id,
    )
    return submission


def _failure_status(category: str) -> int:
    return {
        "configuration": 503,
        "rate_limited": 503,
        "provider_rejected": 502,
        "provider_timeout": 504,
        "provider_unavailable": 503,
        "unknown": 502,
    }.get(category, 502)


def _claim_email_attempt(db: Session, submission: SupportMessage) -> bool:
    """Atomically claim one live provider call, recovering stale claims."""
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(minutes=2)
    claimed = (
        db.query(SupportMessage)
        .filter(SupportMessage.id == submission.id)
        .filter(
            or_(
                SupportMessage.email_status.in_(("pending", "failed")),
                and_(
                    SupportMessage.email_status == "sending",
                    SupportMessage.updated_at < stale_before,
                ),
            )
        )
        .update(
            {
                SupportMessage.email_status: "sending",
                SupportMessage.failure_category: None,
                SupportMessage.attempt_count: SupportMessage.attempt_count + 1,
                SupportMessage.updated_at: now,
            },
            synchronize_session=False,
        )
    )
    db.commit()
    db.refresh(submission)
    return claimed == 1


@router.post("/contact", response_model=SupportMessageResponse, status_code=200)
@limiter.limit("10/hour")
async def send_support_message(
    request: Request,
    payload: SupportMessageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> SupportMessageResponse:
    submission = _resolve_submission(
        db,
        payload=payload,
        user_id=current_user.id,
    )

    if submission.email_status == "sent":
        return SupportMessageResponse(
            request_id=submission.request_id,
            status="sent",
        )

    if not _claim_email_attempt(db, submission):
        if submission.email_status == "sent":
            return SupportMessageResponse(
                request_id=submission.request_id,
                status="sent",
            )
        raise HTTPException(
            status_code=409,
            detail="This support request is already being processed. Please try again shortly.",
        )

    logger.info(
        "[SUPPORT] Email attempt started | request_id=%s | user_id=%s | attempt=%s",
        submission.request_id,
        current_user.id,
        submission.attempt_count,
    )

    user_name = (
        f"{current_user.first_name or ''} {current_user.last_name or ''}".strip()
        or "Unknown"
    )
    try:
        provider_message_id = await asyncio.to_thread(
            support_email_service.send_support_email,
            request_id=submission.request_id,
            user_name=user_name,
            user_email=current_user.email or "",
            user_role=current_user.role or "unknown",
            subject=submission.subject,
            message=submission.message,
            submitted_at=submission.created_at,
        )
    except support_email_service.SupportEmailDeliveryError as exc:
        submission.email_status = "failed"
        submission.failure_category = exc.category
        submission.provider_message_id = None
        submission.sent_at = None
        submission.updated_at = datetime.now(timezone.utc)
        db.commit()
        logger.warning(
            "[SUPPORT] Email attempt failed | request_id=%s | user_id=%s | category=%s",
            submission.request_id,
            current_user.id,
            exc.category,
        )
        raise HTTPException(
            status_code=_failure_status(exc.category),
            detail=_RETRYABLE_DETAIL,
        ) from None

    sent_at = datetime.now(timezone.utc)
    submission.email_status = "sent"
    submission.provider_message_id = provider_message_id
    submission.failure_category = None
    submission.sent_at = sent_at
    submission.updated_at = sent_at
    db.commit()

    logger.info(
        "[SUPPORT] Email accepted | request_id=%s | user_id=%s | provider_message_id=%s",
        submission.request_id,
        current_user.id,
        provider_message_id,
    )
    return SupportMessageResponse(
        request_id=submission.request_id,
        status="sent",
    )
