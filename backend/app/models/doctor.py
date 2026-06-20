
from sqlalchemy import (
    Boolean,
    Column,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import relationship
from app.core.database import Base

class Doctor(Base):
    __tablename__ = "doctors"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    
    full_name = Column(String, index=True)
    specialty = Column(String, index=True)
    bio = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    
    # Legacy field retained temporarily while appointment booking is migrated.
    # It is kept synchronized with consultation_fee by the profile endpoint.
    hourly_rate = Column(Float, default=4000.0)
    consultation_fee = Column(Float, nullable=False, default=4000.0)
    consultation_duration_minutes = Column(Integer, nullable=False, default=30)
    rating = Column(Float, default=5.0)
    review_count = Column(Integer, default=0)
    years_experience = Column(Integer, default=1) # <--- NEW FIELD
    
    is_available = Column(Boolean, default=False)
    license_number = Column(String, unique=True, index=True)
    mdcn_license_url = Column(String, nullable=True) # NEW
    indemnity_cert_url = Column(String, nullable=True) # NEW
    status = Column(String, default="pending", index=True) # "pending", "active", "rejected"
    rejection_reason = Column(String, nullable=True)  # Admin's reason for rejection
    is_verified = Column(Boolean, default=False, index=True)
    documents_url = Column(String, nullable=True)

    # --- 💳 PAYSTACK SUBACCOUNT (added 2026-04-22) ---
    # Stored after a doctor completes bank onboarding. Used to route commission
    # splits automatically at the Paystack gateway level.
    bank_code = Column(String, nullable=True)               # e.g. "058" (GTBank)
    account_number = Column(String, nullable=True)           # 10-digit NUBAN
    paystack_subaccount_code = Column(String, nullable=True) # e.g. "SUB_abc123"
    paystack_recipient_code = Column(String, nullable=True)  # e.g. "RCP_abc123"
    total_earnings = Column(Numeric(14, 2), nullable=False, default=0)

    user = relationship("User")

