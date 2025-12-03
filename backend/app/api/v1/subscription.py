from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from app.core.database import get_db
from app.models.user import User
from app.api import deps
from app.schemas.user import UserResponse

router = APIRouter()

@router.post("/upgrade", response_model=UserResponse)
def upgrade_to_premium(
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user)):
    
    current_user.plan = "premium"
    current_user.subscription_expiry = datetime.utcnow() + timedelta(days=30)
    
    db.commit()
    db.refresh(current_user)
    
    return current_user