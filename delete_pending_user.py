import sys
import os

# Add backend to path so we can import 'app'
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.user import User
from app.models.doctor import Doctor
from dotenv import load_dotenv

# Load env variables
load_dotenv("backend/.env")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("❌ DATABASE_URL not found in backend/.env")
    exit(1)

# Handle Postgres connection string
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
db = SessionLocal()

def delete_user(email):
    print(f"Searching for user: {email}...")
    user = db.query(User).filter(User.email == email).first()
    
    if not user:
        print(f"User {email} not found.")
        return

    print(f"Found User ID: {user.id}")

    # Check for Doctor Profile
    doctor = db.query(Doctor).filter(Doctor.user_id == user.id).first()
    if doctor:
        print(f"Found Doctor Profile (ID: {doctor.id}). Deleting that first...")
        db.delete(doctor)
    
    # Delete User
    print(f"Deleting User {email}...")
    db.delete(user)
    db.commit()
    print("DELETION COMPLETE. You can now register again.")

if __name__ == "__main__":
    target_email = "jennynlongs@gmail.com"
    delete_user(target_email)
