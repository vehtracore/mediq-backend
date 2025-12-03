
from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime

class SlotCreate(BaseModel):
    doctor_id: int
    start_time: datetime

class SlotResponse(BaseModel):
    id: int
    doctor_id: int
    start_time: datetime
    is_booked: bool
    model_config = ConfigDict(from_attributes=True)

class AppointmentCreate(BaseModel):
    slot_id: int
    notes: Optional[str] = None

class AppointmentResponse(BaseModel):
    id: int
    doctor_name: str
    status: str
    payment_status: str
    start_time: datetime
    notes: Optional[str] = None
    amount: float = 0.0
    has_review: bool = False # <--- NEW FIELD

    model_config = ConfigDict(from_attributes=True)

class GeneralBookRequest(BaseModel):
    notes: str
