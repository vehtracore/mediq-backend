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

print("🔍 Scanning for inconsistent Doctor accounts...")
# Find doctors who are verified but their user account is NOT active
doctors = db.query(Doctor).filter(Doctor.is_verified == True).all()
count = 0

for doc in doctors:
    user = db.query(User).filter(User.id == doc.user_id).first()
    if user and not user.is_active:
        print(f"🛠️ Fixing Dr. {doc.full_name} ({user.email})...")
        user.is_active = True
        count += 1

if count > 0:
    db.commit()
    print(f"✅ Fixed {count} accounts. They should be able to log in now.")
else:
    print("✅ No inconsistent accounts found.")
