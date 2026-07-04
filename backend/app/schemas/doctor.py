
from pydantic import BaseModel, ConfigDict, EmailStr, field_validator
from typing import Literal, Optional

class DoctorBase(BaseModel):
    full_name: str
    specialty: str
    bio: Optional[str] = None
    image_url: Optional[str] = None
    hourly_rate: Optional[float] = 4000.0
    consultation_fee: Optional[float] = 4000.0
    consultation_duration_minutes: Optional[int] = 30
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
    # Banking / Paystack subaccount (nullable until doctor completes payout setup)
    bank_code: Optional[str] = None
    account_number: Optional[str] = None
    paystack_subaccount_code: Optional[str] = None
    paystack_recipient_code: Optional[str] = None
    total_earnings: Optional[float] = 0.0
    model_config = ConfigDict(from_attributes=True)

class DoctorRegister(BaseModel):
    email: str
    password: str
    full_name: str
    specialty: str
    license_number: str


class DoctorRegistrationPreflight(BaseModel):
    email: EmailStr
    license_number: str

    @field_validator("license_number")
    @classmethod
    def validate_license_number(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("License number is required.")
        return normalized


class DoctorUpdate(BaseModel):
    bio: Optional[str] = None
    consultation_fee: Optional[float] = None
    consultation_duration_minutes: Optional[Literal[30]] = None
    years_experience: Optional[int] = None # <--- NEW
    image_url: Optional[str] = None

class ReapplyRequest(BaseModel):
    """Payload a rejected doctor submits when re-applying for verification."""
    license_number: Optional[str] = None          # Corrected MDCN number
    mdcn_license_url: Optional[str] = None        # New Cloudinary URL for license image
    indemnity_cert_url: Optional[str] = None      # New Cloudinary URL for indemnity cert


class PayoutSettingsRequest(BaseModel):
    """Payload for PUT /api/v1/doctors/me/payout-settings."""
    bank_code: str      # Paystack bank code, e.g. '058' for GTBank
    account_number: str # 10-digit NUBAN

    @field_validator("bank_code")
    @classmethod
    def validate_bank_code(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.isdigit() or not 3 <= len(normalized) <= 6:
            raise ValueError("Bank code must be 3 to 6 digits.")
        return normalized

    @field_validator("account_number")
    @classmethod
    def validate_account_number(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.isdigit() or len(normalized) != 10:
            raise ValueError("Account number must be a 10-digit NUBAN.")
        return normalized
