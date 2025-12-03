
from pydantic import BaseModel, ConfigDict
from typing import Optional

class DoctorBase(BaseModel):
    full_name: str
    specialty: str
    bio: Optional[str] = None
    image_url: Optional[str] = None
    hourly_rate: float
    rating: float
    review_count: int
    years_experience: int # <--- NEW
    is_available: bool
    is_verified: bool

class DoctorResponse(DoctorBase):
    id: int
    user_id: int
    license_number: str 
    model_config = ConfigDict(from_attributes=True)

class DoctorRegister(BaseModel):
    email: str
    password: str
    full_name: str
    specialty: str
    license_number: str

class DoctorUpdate(BaseModel):
    bio: Optional[str] = None
    hourly_rate: Optional[float] = None
    years_experience: Optional[int] = None # <--- NEW
    image_url: Optional[str] = None
