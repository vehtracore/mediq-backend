
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.models.doctor import Doctor
from app.models.user import User
from app.models.appointment import Appointment
from app.schemas.doctor import DoctorResponse, DoctorUpdate
from app.api import deps

router = APIRouter()

@router.get("/", response_model=List[DoctorResponse])
def read_doctors(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return db.query(Doctor).filter(Doctor.is_verified == True).offset(skip).limit(limit).all()

@router.get("/stats")
def get_doctor_stats(db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    if current_user.role != "doctor": raise HTTPException(403, "Not a doctor")
    
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    if not doctor: raise HTTPException(404, "Profile not found")
    
    # 1. Calculate Earnings (Sum of payout for completed/paid appts)
    earnings = 0.0
    paid_appts = db.query(Appointment).filter(Appointment.doctor_id == doctor.id, Appointment.payment_status == "paid").all()
    for a in paid_appts:
        earnings += a.payout

    # 2. Calculate Unique Patients
    patient_ids = set()
    all_appts = db.query(Appointment).filter(Appointment.doctor_id == doctor.id).all()
    for a in all_appts:
        patient_ids.add(a.patient_id)
    
    return {
        "earnings": earnings,
        "total_patients": len(patient_ids),
        "rating": doctor.rating,
        "reviews": doctor.review_count,
        "years_experience": doctor.years_experience
    }

@router.put("/me", response_model=DoctorResponse)
def update_doctor_me(data: DoctorUpdate, db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    if not doctor: raise HTTPException(404, "Not found")

    if data.bio: doctor.bio = data.bio
    if data.hourly_rate: doctor.hourly_rate = data.hourly_rate
    if data.years_experience: doctor.years_experience = data.years_experience
    if data.image_url: doctor.image_url = data.image_url

    db.commit()
    db.refresh(doctor)
    return doctor

@router.get("/{doctor_id}", response_model=DoctorResponse)
def read_doctor(doctor_id: int, db: Session = Depends(get_db)):
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor: raise HTTPException(404, "Doctor not found")
    return doctor
