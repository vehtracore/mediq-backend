import sys
import os

# Add backend to path so we can import 'app'
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.database import Base
from app.models.user import User
from app.models.doctor import Doctor
from dotenv import load_dotenv

load_dotenv("backend/.env")

# Use direct connection for CLI (bypass pooler issues if any, or just use what we have)
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("❌ DATABASE_URL not found in backend/.env")
    exit(1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
db = SessionLocal()

def list_pending():
    print("\n🔍 Scanning for PENDING Doctors...")
    pending_docs = db.query(Doctor).filter(Doctor.status == 'pending').all()
    
    if not pending_docs:
        print("✅ No pending doctors found.")
        return []
    
    results = []
    print(f"{'ID':<5} | {'Name':<25} | {'License':<15} | {'Email'}")
    print("-" * 60)
    for doc in pending_docs:
        user = db.query(User).filter(User.id == doc.user_id).first()
        email = user.email if user else "UNKNOWN"
        print(f"{doc.id:<5} | {doc.full_name:<25} | {doc.license_number:<15} | {email}")
        results.append(doc)
    print("-" * 60)
    return results

def approve(doc_id):
    doc = db.query(Doctor).filter(Doctor.id == doc_id).first()
    if not doc:
        print(f"❌ Doctor ID {doc_id} not found.")
        return
    
    user = db.query(User).filter(User.id == doc.user_id).first()
    
    print(f"🚀 Approving Dr. {doc.full_name} ({user.email})...")
    doc.status = "active"
    doc.is_verified = True
    if user:
        user.is_active = True
    
    db.commit()
    print("✅ APPROVED! User can now log in.")

if __name__ == "__main__":
    docs = list_pending()
    if docs:
        choice = input("\nEnter Doctor ID to approve (or 'q' to quit): ")
        if choice.lower() != 'q' and choice.isdigit():
            approve(int(choice))
