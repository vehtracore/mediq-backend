from fastapi import APIRouter, HTTPException, status, Depends, Request
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from pydantic import BaseModel, HttpUrl
from typing import Optional

from app.services import ai_service
from app.core.database import get_db
from app.models.user import User
from app.api import deps
from app.core.limiter import limiter

router = APIRouter()

class ChatRequest(BaseModel):
    message: str
    image_url: Optional[str] = None
    history: Optional[list] = None
    language: Optional[str] = "English"  # <--- Language selection field


class ChatResponse(BaseModel):
    response: str

@router.post("/analyze", response_model=ChatResponse)
@limiter.limit("10/minute")
async def analyze_symptoms(
    request: Request,
    chat_request: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user)
):
    if not chat_request.message.strip() and not chat_request.image_url:
        raise HTTPException(status_code=400, detail="Message or Image is required")

    now = datetime.utcnow()
    today = now.date()

    # ── 1. Inline daily reset ────────────────────────────────────────────────
    # If the user's last_chat_date is before today (or has never been set),
    # roll the counter back to zero so the new day starts fresh.
    # This avoids any background cron job — the reset is lazy and happens on
    # the first request of each day.
    if current_user.last_chat_date is None or current_user.last_chat_date < today:
        current_user.daily_chat_count = 0
        current_user.last_chat_date = today

    # ── 2. Enforce daily quota ───────────────────────────────────────────────
    # Free    →  3 AI diagnostic messages per day
    # Premium → 30 AI diagnostic messages per day
    # Family  → 30 AI diagnostic messages per day (same as Premium)
    _PAID_PLANS = {"premium", "family"}
    daily_limit: int = 30 if current_user.plan in _PAID_PLANS else 3

    if current_user.daily_chat_count >= daily_limit:
        raise HTTPException(
            status_code=429,
            detail=(
                "Daily AI diagnostic limit reached. "
                "Please try again tomorrow or upgrade your plan."
            ),
        )

    # ── 3. Build user context for the AI ────────────────────────────────────
    user_age = "Unknown"
    if current_user.dob:
        user_age = (today - current_user.dob).days // 365

    user_context = {
        "age": f"{user_age} years old",
        "conditions": current_user.chronic_conditions or "None",
    }

    # ── 4. Call Gemini ───────────────────────────────────────────────────────
    target_language = chat_request.language or "English"

    ai_response = await ai_service.get_medical_response(
        chat_request.message,
        history=chat_request.history,
        image_url=chat_request.image_url,
        user_context=user_context,
        target_language=target_language,
    )

    # ── 5. Persist updated counters ──────────────────────────────────────────
    current_user.daily_chat_count += 1
    current_user.burst_chat_count += 1

    db.add(current_user)
    db.commit()

    return ChatResponse(response=ai_response)