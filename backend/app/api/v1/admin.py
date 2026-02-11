from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from app.api.v1.auth import send_email  # Import email helper
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel
from app.core.database import get_db
from app.models.user import User
from app.models.doctor import Doctor
from app.models.appointment import Appointment
from app.models.audit import AuditLog
from app.schemas.user import UserResponse
from app.schemas.doctor import DoctorResponse
from app.api import deps

router = APIRouter()

def get_current_admin(current_user: User = Depends(deps.get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access only")
    return current_user

class AdminStats(BaseModel):
    total_users: int
    total_doctors: int
    pending_verifications: int
    total_revenue: float
    active_appointments: int

@router.get("/stats", response_model=AdminStats)
def get_admin_stats(db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    total_users = db.query(User).filter(User.role == "patient").count()
    total_doctors = db.query(User).filter(User.role == "doctor").count()
    pending_verifications = db.query(Doctor).filter(Doctor.is_verified == False).count()
    
    paid_appts = db.query(Appointment).filter(Appointment.payment_status == "paid").all()
    total_revenue = sum(a.amount for a in paid_appts)
    
    active_appointments = db.query(Appointment).filter(Appointment.status.in_(["pending", "confirmed"])).count()

    return {
        "total_users": total_users,
        "total_doctors": total_doctors,
        "pending_verifications": pending_verifications,
        "total_revenue": total_revenue,
        "active_appointments": active_appointments
    }

@router.get("/users", response_model=List[UserResponse])
def get_all_users(role: Optional[str] = None, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    query = db.query(User)
    if role: query = query.filter(User.role == role)
    return query.all()

@router.put("/users/{user_id}/suspend")
def suspend_user(user_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user: raise HTTPException(404, "User not found")
    user.is_banned = not user.is_banned
    db.commit()
    status = "suspended" if user.is_banned else "active"
    return {"message": f"User is now {status}."}

# --- NEW: FETCH PENDING DOCTORS ---
@router.get("/doctors/pending", response_model=List[DoctorResponse])
def get_pending_doctors(db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    # Fetch ONLY unverified doctors
    return db.query(Doctor).filter(Doctor.is_verified == False).all()

@router.put("/doctors/{doctor_id}/verify")
def verify_doctor(doctor_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor: raise HTTPException(404, "Doctor not found")
    
    user = db.query(User).filter(User.id == doctor.user_id).first()
    if not user: raise HTTPException(404, "User for doctor not found")

    # ✅ FIX: Set ALL required fields for login to work
    doctor.is_verified = True
    doctor.is_available = True
    doctor.status = "active"  # <-- THIS WAS MISSING!
    user.is_active = True
    
    db.commit()
    
    # ✅ FIX: Send email notification to the doctor
    background_tasks.add_task(
        send_email,
        user.email,
        "MedIQ: Your Application is Approved!",
        f"Congratulations Dr. {doctor.full_name}!\n\nYour MedIQ doctor account is now active. You can log in and start accepting patients."
    )
    
    return {"message": "Doctor verified and account activated."}

@router.delete("/doctors/{doctor_id}/reject")
def reject_doctor(doctor_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor: raise HTTPException(404, "Doctor not found")
    if user_to_delete: db.delete(user_to_delete)
    db.commit()
    return {"message": "Doctor application rejected and account removed."}

# --- 🛠️ TEMP: DATABASE MIGRATION HELPER ---
from sqlalchemy import text
@router.post("/fix-schema")
def fix_schema(db: Session = Depends(get_db)):
    """Run this ONCE to add the missing column"""
    try:
        # PostgreSQL specific command
        db.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS image_url VARCHAR;"))
        db.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS verification_token VARCHAR;"))
        # Backfill: existing users (created before verification) should be verified
        db.execute(text("UPDATE users SET is_verified = TRUE WHERE is_verified IS NULL OR is_verified = FALSE;"))
        db.commit()
        return {"message": "✅ Schema updated + existing users marked as verified."}
    except Exception as e:
        return {"message": f"❌ Error updating schema: {e}"}

# --- 🛠️ TEMP: Delete test users ---
@router.post("/delete-test-users")
def delete_test_users(emails: dict, db: Session = Depends(get_db)):
    """Delete test users by email list. Body: {"emails": ["a@b.com"]}"""
    try:
        deleted = []
        for email in emails.get("emails", []):
            user = db.query(User).filter(User.email == email).first()
            if user:
                db.delete(user)
                deleted.append(email)
        db.commit()
        return {"message": f"Deleted {len(deleted)} users", "deleted": deleted}
    except Exception as e:
        db.rollback()
        return {"message": f"Error: {e}"}