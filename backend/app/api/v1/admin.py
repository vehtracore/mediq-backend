from fastapi import APIRouter, Depends, HTTPException, status
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
def verify_doctor(doctor_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor: raise HTTPException(404, "Doctor not found")
    doctor.is_verified = True
    doctor.is_available = True 
    db.commit()
    return {"message": "Doctor verified."}

@router.delete("/doctors/{doctor_id}/reject")
def reject_doctor(doctor_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor: raise HTTPException(404, "Doctor not found")
    user_to_delete = db.query(User).filter(User.id == doctor.user_id).first()
    db.delete(doctor)
    if user_to_delete: db.delete(user_to_delete)
    db.commit()
    return {"message": "Doctor application rejected and account removed."}