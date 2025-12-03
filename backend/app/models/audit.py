from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from datetime import datetime
from app.core.database import Base

class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    admin_id = Column(Integer, ForeignKey("users.id"))
    resource = Column(String) # e.g., "Chat: 123"
    reason = Column(String)   # e.g., "Security Audit"
    timestamp = Column(DateTime, default=datetime.utcnow)