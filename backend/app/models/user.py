from sqlalchemy import Column, Integer, String, Boolean, Date, DateTime
from app.core.database import Base
from datetime import datetime

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    
    # --- BASIC PROFILE ---
    first_name = Column(String, index=True)
    last_name = Column(String, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    dob = Column(Date, nullable=True)
    location = Column(String, nullable=True)
    # image_url = Column(String, nullable=True) # ✅ NEW COLUMN
    # is_verified = Column(Boolean, default=False) # ✅ NEW: Email Verification
    
    # --- ROLE & STATUS ---
    role = Column(String, default="patient")
    is_active = Column(Boolean, default=True)
    is_banned = Column(Boolean, default=False)
    
    # --- SUBSCRIPTION & LIMITS ---
    plan = Column(String, default="free") # 'free' or 'premium'
    subscription_expiry = Column(DateTime, nullable=True)
    
    # Chat Limits
    daily_chat_count = Column(Integer, default=0)
    last_chat_date = Column(Date, nullable=True)
    burst_chat_count = Column(Integer, default=0)
    burst_start_time = Column(DateTime, nullable=True)

    # --- 🏥 NEW: MEDICAL HISTORY ---
    blood_type = Column(String, nullable=True)
    allergies = Column(String, nullable=True)         # Store as text "Peanuts, Penicillin"
    chronic_conditions = Column(String, nullable=True) # "Asthma, Diabetes"
    medications = Column(String, nullable=True)       # "Ibuprofen, Insulin"
    past_surgeries = Column(String, nullable=True)    # "Appendectomy 2015"

    # --- ⚙️ NEW: SETTINGS ---
    settings_theme = Column(String, default="light")  # 'light' or 'dark'
    settings_notifications = Column(Boolean, default=True)
    settings_email_updates = Column(Boolean, default=False)