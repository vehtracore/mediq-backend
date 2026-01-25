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
class UserCreate(UserBase):
    password: str

# --- 🚀 UPDATED: User Update (Includes Medical & Settings) ---
class UserUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    location: Optional[str] = None
    dob: Optional[date] = None
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

# --- 🚀 UPDATED: User Response (Includes Medical & Settings) ---
class UserResponse(UserBase):
    id: int
    is_active: bool
    id: int
    is_active: bool
    image_url: Optional[str] = None # ✅ ADDED
    is_verified: Optional[bool] = False # ✅ Optional: column may not exist in prod DB
    
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

    model_config = ConfigDict(from_attributes=True)

# Auth Schemas
class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str