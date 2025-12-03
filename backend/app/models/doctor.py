
from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base

class Doctor(Base):
    __tablename__ = "doctors"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    
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
    is_verified = Column(Boolean, default=False)
    documents_url = Column(String, nullable=True) 

    user = relationship("User")
