
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Float
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base
from app.models.user import User 

class DoctorSlot(Base):
    __tablename__ = "doctor_slots"
    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), index=True)
    start_time = Column(DateTime, index=True)
    is_booked = Column(Boolean, default=False)
    doctor = relationship("Doctor", backref="slots")

class Appointment(Base):
    __tablename__ = "appointments"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("users.id"), index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=True, index=True)
    slot_id = Column(Integer, ForeignKey("doctor_slots.id"), unique=True, nullable=True)
    start_time = Column(DateTime, default=datetime.utcnow, index=True)
    status = Column(String, default="pending", index=True)
    payment_status = Column(String, default="unpaid")
    is_acknowledged = Column(Boolean, default=False)
    notes = Column(String, nullable=True)
    related_appointment_id = Column(Integer, nullable=True)
    amount = Column(Float, default=0.0)
    commission = Column(Float, default=0.0)
    payout = Column(Float, default=0.0)
    # Paystack reference embedded at checkout — used by the payment watchdog
    paystack_reference = Column(String, nullable=True, index=True)
    # --- Continuity of Care: Physical Referral ---
    referred_hospital = Column(String, nullable=True)   # e.g. "Lagos Island General Hospital A&E"
    referral_note = Column(String, nullable=True)        # Standardised referral string

    patient = relationship("User")
    doctor = relationship("Doctor")
    slot = relationship("DoctorSlot", backref="appointment", uselist=False)
    # NEW: Link to review
    review = relationship("Review", back_populates="appointment", uselist=False)
