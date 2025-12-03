from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from pydantic import BaseModel

from app.services import ai_service
from app.core.database import get_db
from app.models.user import User
from app.api import deps

router = APIRouter()

class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    response: str

@router.post("/analyze", response_model=ChatResponse)
async def analyze_symptoms(
    request: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user)
):
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    now = datetime.utcnow()
    today = now.date()

    # 1. DAILY RESET
    if current_user.last_chat_date != today:
        current_user.daily_chat_count = 0
        current_user.last_chat_date = today
        # Reset burst on new day too just in case
        current_user.burst_chat_count = 0 
        current_user.burst_start_time = now

    # 2. FREE TIER LIMIT
    if current_user.plan == "free":
        if current_user.daily_chat_count >= 5:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Free tier limit reached (5 chats/day). Please upgrade to Premium."
            )

    # 3. BURST LIMIT (Anti-Spam protection for everyone)
    # Reset burst window if 1 hour has passed
    if not current_user.burst_start_time or (now - current_user.burst_start_time) > timedelta(hours=1):
        current_user.burst_start_time = now
        current_user.burst_chat_count = 0
    
    if current_user.burst_chat_count >= 30:
        raise HTTPException(
            status_code=429, # Too Many Requests
            detail="You are chatting too fast. Please take a break."
        )

    # 4. Process Request
    ai_response = await ai_service.get_medical_response(request.message)

    # 5. Increment Counters
    current_user.daily_chat_count += 1
    current_user.burst_chat_count += 1
    
    db.add(current_user)
    db.commit()

    return ChatResponse(response=ai_response)