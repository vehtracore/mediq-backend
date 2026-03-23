from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.core.database import Base
from datetime import datetime


class LabResult(Base):
    """
    Stores urinalysis test strip scan results.
    Each record represents one scan analysis by Gemini Vision.
    """
    __tablename__ = "lab_results"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # --- IMAGE PROOF ---
    image_url = Column(String, nullable=True)  # Cloudinary URL of the scanned strip
    
    # --- AI ANALYSIS ---
    raw_data = Column(JSON, nullable=True)  # Full AI response with all readings
    lighting_score = Column(String, nullable=True)  # "Good", "Poor", "Acceptable"
    
    # --- VERIFICATION ---
    is_verified = Column(Boolean, default=False)  # User confirmation of accuracy
    
    # --- TIMESTAMPS ---
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    # --- RELATIONSHIPS ---
    user = relationship("User", backref="lab_results")
