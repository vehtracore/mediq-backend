from sqlalchemy import Column, Integer, String, Boolean, Date, DateTime, ForeignKey
from sqlalchemy.orm import relationship, backref
from sqlalchemy import func
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
    image_url = Column(String, nullable=True)
    is_verified = Column(Boolean, default=False, index=True)
    verification_token = Column(String, nullable=True)
    auth_provider = Column(String, nullable=True, default=None)  # "google" | None (password)
    
    # --- ROLE & STATUS ---
    role = Column(String, default="patient", index=True)
    is_active = Column(Boolean, default=True, index=True)
    is_banned = Column(Boolean, default=False)
    
    # --- SUBSCRIPTION & LIMITS ---
    plan = Column(String, default="free")  # 'free' or 'premium'
    subscription_expiry = Column(DateTime, nullable=True)
    
    # Chat Limits
    daily_chat_count = Column(Integer, default=0)
    last_chat_date = Column(Date, nullable=True)
    burst_chat_count = Column(Integer, default=0)
    burst_start_time = Column(DateTime, nullable=True)

    # Lab / Gemini Vision Limits
    # Tracks how many AI urinalysis scans the user has made this calendar month.
    # Reset inline: when last_lab_reset is not in the current year+month, the
    # endpoint zeroes monthly_lab_count before checking the cap.
    monthly_lab_count = Column(Integer, default=0, nullable=False)
    last_lab_reset = Column(Date, nullable=True)

    # --- 👨‍👩‍👧 FAMILY PLAN ---
    # Self-referential FK. NULL → this user is a primary account holder.
    # Non-null → this user is a dependent linked to the given primary user ID.
    # ON DELETE SET NULL ensures removing the primary account unlinks dependents
    # gracefully rather than cascade-deleting them.
    primary_account_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    # Bidirectional relationship:
    #   primary_user.dependents  → list of User objects linked to this account
    #   dependent_user.primary_account → the User object they are linked under
    dependents = relationship(
        "User",
        backref=backref("primary_account", remote_side="User.id"),
        foreign_keys=[primary_account_id],
    )

    # --- 🏥 MEDICAL HISTORY ---
    blood_type = Column(String, nullable=True)
    allergies = Column(String, nullable=True)          # Store as text "Peanuts, Penicillin"
    chronic_conditions = Column(String, nullable=True)  # "Asthma, Diabetes"
    medications = Column(String, nullable=True)        # "Ibuprofen, Insulin"
    past_surgeries = Column(String, nullable=True)     # "Appendectomy 2015"

    # --- ⚙️ SETTINGS ---
    settings_theme = Column(String, default="light")   # 'light' or 'dark'
    settings_notifications = Column(Boolean, default=True)
    settings_email_updates = Column(Boolean, default=False)

    # --- 🚨 EMERGENCY PROTOCOL ---
    # Next of Kin phone in international format e.g. '+2348012345678'
    kin_phone = Column(String, nullable=True)
    # Per-channel toggle
    emergency_sms_enabled = Column(Boolean, default=False)
    # Rate-limiting / quota tracking for NOK SMS
    last_emergency_trigger = Column(DateTime(timezone=True), nullable=True)
    emergency_sms_count = Column(Integer, default=0, nullable=False)

    # --- 📲 PUSH NOTIFICATIONS ---
    fcm_token = Column(String, nullable=True)

    # --- ⚖️ NDPA 30-DAY LEGAL HOLD ---
    # Set when user requests deletion. A daily scrubber anonymises PII 30 days
    # after this timestamp, satisfying Nigerian Data Protection Act retention rules.
    deletion_requested_at = Column(DateTime(timezone=True), nullable=True, index=True)