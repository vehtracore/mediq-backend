
from pydantic import BaseModel, ConfigDict
from typing import Optional

class DoctorBase(BaseModel):
    full_name: str
    specialty: str
    bio: Optional[str] = None
    image_url: Optional[str] = None
    hourly_rate: Optional[float] = 0.0
    rating: Optional[float] = 5.0
    review_count: Optional[int] = 0
    years_experience: Optional[int] = 1
    is_available: Optional[bool] = False
    is_verified: Optional[bool] = False

class DoctorResponse(DoctorBase):
    id: int
    user_id: int
    license_number: Optional[str] = None
    mdcn_license_url: Optional[str] = None
    indemnity_cert_url: Optional[str] = None
    status: Optional[str] = "pending"           # 'pending' | 'active' | 'rejected'
    rejection_reason: Optional[str] = None       # Set by admin on rejection
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

class ReapplyRequest(BaseModel):
    """Payload a rejected doctor submits when re-applying for verification."""
    license_number: Optional[str] = None          # Corrected MDCN number
    mdcn_license_url: Optional[str] = None        # New Cloudinary URL for license image
    indemnity_cert_url: Optional[str] = None      # New Cloudinary URL for indemnity cert
