from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime

class HealthTipBase(BaseModel):
    title: str
    category: str
    read_time: str
    image_url: Optional[str] = None
    content: str

class HealthTipCreate(HealthTipBase):
    pass

class HealthTipUpdate(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None
    read_time: Optional[str] = None
    image_url: Optional[str] = None
    content: Optional[str] = None

class HealthTipResponse(HealthTipBase):
    id: int
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)