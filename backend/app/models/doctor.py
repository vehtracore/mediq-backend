
from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey
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
    
    hourly_rate = Column(Float, default=0.0)
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

    user = relationship("User")

