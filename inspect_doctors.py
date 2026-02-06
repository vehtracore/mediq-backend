import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.user import User
from app.models.doctor import Doctor
from dotenv import load_dotenv

load_dotenv("backend/.env")
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
db = SessionLocal()

print(f"\n{'DocID':<5} | {'UserEmail':<25} | {'DocVerified':<12} | {'UserActive':<10} | {'Status'}")
print("-" * 70)

doctors = db.query(Doctor).all()
for doc in doctors:
    user = db.query(User).filter(User.id == doc.user_id).first()
    email = user.email if user else "ORPHAN"
    is_active = str(user.is_active) if user else "N/A"
    
    print(f"{doc.id:<5} | {email:<25} | {str(doc.is_verified):<12} | {is_active:<10} | {doc.status}")

print("-" * 70)
