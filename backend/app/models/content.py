from sqlalchemy import Column, Integer, String, DateTime, Text
from datetime import datetime
from app.core.database import Base

class HealthTip(Base):
    __tablename__ = "health_tips"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    category = Column(String, index=True)
    read_time = Column(String) # e.g., "5 min read"
    image_url = Column(String, nullable=True)
    content = Column(Text) # Full article text
    created_at = Column(DateTime, default=datetime.utcnow)