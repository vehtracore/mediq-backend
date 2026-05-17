from pydantic import BaseModel, EmailStr, ConfigDict
from typing import Optional
from datetime import date

# Base schema with shared fields
class UserBase(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    dob: date 
    location: Optional[str] = None
    role: Optional[str] = "patient"

# Properties to receive via API on creation
# NOTE: password is optional — Supabase Auth owns the credential.
# This field is retained temporarily for backward compatibility but ignored by the endpoint.
class UserCreate(UserBase):
    password: Optional[str] = None

# --- 🚀 UPDATED: User Update (Includes Medical & Settings) ---
class UserUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    location: Optional[str] = None
    dob: Optional[date] = None
    image_url: Optional[str] = None # ✅ ADDED
    
    # Medical History
    blood_type: Optional[str] = None
    allergies: Optional[str] = None
    chronic_conditions: Optional[str] = None
    medications: Optional[str] = None
    past_surgeries: Optional[str] = None

    # Settings
    settings_theme: Optional[str] = None
    settings_notifications: Optional[bool] = None
    settings_email_updates: Optional[bool] = None

    # Emergency Protocol
    kin_phone: Optional[str] = None
    emergency_sms_enabled: Optional[bool] = None

# --- 🚀 UPDATED: User Response (Includes Medical & Settings) ---
class UserResponse(UserBase):
    id: int
    # is_active / is_banned / plan: all use Optional so that legacy DB rows with NULL
    # values (before the relevant column was added with a DEFAULT) do not trigger a
    # Pydantic ResponseValidationError and crash the /me endpoint.
    is_active: Optional[bool] = True
    is_banned: Optional[bool] = False
    plan: Optional[str] = "free"          # NULL in DB → treated as "free"
    image_url: Optional[str] = None
    is_verified: Optional[bool] = False
    
    # Medical History
    blood_type: Optional[str] = None
    allergies: Optional[str] = None
    chronic_conditions: Optional[str] = None
    medications: Optional[str] = None
    past_surgeries: Optional[str] = None

    # Settings
    settings_theme: Optional[str] = "light"
    settings_notifications: Optional[bool] = True
    settings_email_updates: Optional[bool] = False

    # Emergency Protocol
    kin_phone: Optional[str] = None
    emergency_sms_enabled: Optional[bool] = False

    # Family Plan
    primary_account_id: Optional[int] = None
    dependents: Optional[list['DependentUser']] = []

    model_config = ConfigDict(from_attributes=True)

class DependentUser(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: EmailStr
    plan: Optional[str] = "free"   # NULL-safe: mirrors UserResponse.plan
    image_url: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)

# Auth Schemas
class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    doctor_status: Optional[str] = None  # 'active' | 'rejected' | None (non-doctors)

class RefreshRequest(BaseModel):
    refresh_token: str

class DeviceTokenUpdate(BaseModel):
    fcm_token: str