from sqlalchemy import Column, Integer, String, Boolean, Date, DateTime
from app.core.database import Base
from datetime import datetime

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    
    # Profile
    first_name = Column(String, index=True)
    last_name = Column(String, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    dob = Column(Date, nullable=True)
    location = Column(String, nullable=True)
    
    # Role & Status
    role = Column(String, default="patient")
    is_active = Column(Boolean, default=True)
    is_banned = Column(Boolean, default=False)
    
    # --- SUBSCRIPTION & LIMITS ---
    plan = Column(String, default="free") # 'free' or 'premium'
    subscription_expiry = Column(DateTime, nullable=True)
    
    # Chat Limits
    daily_chat_count = Column(Integer, default=0)
    last_chat_date = Column(Date, nullable=True)
    
    # Rate Limiting (Burst protection)
    burst_chat_count = Column(Integer, default=0)
    burst_start_time = Column(DateTime, nullable=True)