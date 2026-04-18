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

    # ... (Limiting logic omitted for brevity, assuming it's unchanged above) ...

    # 4. Process Request (Now with image_url, context, history AND language)
    
    # Calculate Age
    user_age = "Unknown"
    if current_user.dob:
        user_age = (now.date() - current_user.dob).days // 365
        
    user_context = {
        "age": f"{user_age} years old",
        "conditions": current_user.chronic_conditions if current_user.chronic_conditions else "None"
    }

    # Sanitise and pass language to the AI service
    target_language = chat_request.language or "English"

    ai_response = await ai_service.get_medical_response(
        chat_request.message, 
        history=chat_request.history,
        image_url=chat_request.image_url,
        user_context=user_context,
        target_language=target_language
    )

    # 5. Increment Counters
    current_user.daily_chat_count += 1
    current_user.burst_chat_count += 1
    
    db.add(current_user)
    db.commit()

    return ChatResponse(response=ai_response)