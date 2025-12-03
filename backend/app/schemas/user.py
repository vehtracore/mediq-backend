from pydantic import BaseModel, EmailStr, ConfigDict
from typing import Optional
from datetime import date

# Base schema with shared fields
class UserBase(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    # STRICT MODE: DOB is mandatory again
    dob: date 
    location: Optional[str] = None
    role: Optional[str] = "patient"

# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str

# User Update (Fields remain optional here for partial updates)
class UserUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    location: Optional[str] = None
    dob: Optional[date] = None

# Properties to return to client
class UserResponse(UserBase):
    id: int
    is_active: bool

    model_config = ConfigDict(from_attributes=True)

# Auth Schemas
class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str