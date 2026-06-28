import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.database import get_db
from app.models.user import User
from app.api import deps

router = APIRouter()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Allowed report reasons — matches the Flutter dropdown options exactly
# ---------------------------------------------------------------------------
ALLOWED_REASONS = {
    "Inaccurate medical information",
    "Inappropriate content",
    "Other",
}


class AiReportRequest(BaseModel):
    message_text: str = Field(..., min_length=1, max_length=10_000)
    reason: str = Field(..., min_length=1, max_length=200)


class AiReportResponse(BaseModel):
    success: bool


@router.post(
    "/report",
    response_model=AiReportResponse,
    summary="Report an AI-generated message",
    description=(
        "Allows a user to flag a specific AI response for review. "
        "Required for Google Play AI-Generated Content Policy compliance."
    ),
)
def report_ai_message(
    payload: AiReportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> AiReportResponse:
    """
    Persist a user report for a specific AI-generated message.

    The report is stored in the ai_chat_reports table which is
    created idempotently via the startup schema-patch block in main.py.
    """
    if payload.reason not in ALLOWED_REASONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid reason. Must be one of: {', '.join(sorted(ALLOWED_REASONS))}",
        )

    try:
        db.execute(
            text(
                """
                INSERT INTO ai_chat_reports (user_id, message_text, reason, created_at)
                VALUES (:user_id, :message_text, :reason, :created_at)
                """
            ),
            {
                "user_id": current_user.id,
                "message_text": payload.message_text,
                "reason": payload.reason,
                "created_at": datetime.now(timezone.utc),
            },
        )
        db.commit()
        logger.info(
            "[AI REPORT] user_id=%s reason=%r message_length=%d",
            current_user.id,
            payload.reason,
            len(payload.message_text),
        )
        return AiReportResponse(success=True)
    except Exception as exc:
        db.rollback()
        logger.error(
            "[AI REPORT] Failed to save report for user_id=%s: %s",
            current_user.id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save report. Please try again.",
        ) from exc
