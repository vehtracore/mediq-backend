from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime

class ReviewCreate(BaseModel):
    appointment_id: int
    rating: int
    comment: Optional[str] = None

class ReviewResponse(BaseModel):
    id: int
    rating: int
    comment: Optional[str] = None
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)