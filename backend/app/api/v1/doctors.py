
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.models.doctor import Doctor
from app.models.user import User
from app.models.appointment import Appointment
from app.schemas.doctor import DoctorResponse, DoctorUpdate, ReapplyRequest
from app.api import deps

router = APIRouter()

@router.post("/me/reapply", response_model=DoctorResponse)
def reapply_for_verification(
    payload: ReapplyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """
    Allows a rejected doctor to submit corrected documents and re-apply.
    Resets their status back to 'pending' for admin review.
    """
    if current_user.role != "doctor":
        raise HTTPException(status_code=403, detail="Only doctors can reapply")

    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found")

    if doctor.status != "rejected":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reapply: current status is '{doctor.status}'. Only rejected doctors may reapply."
        )

    # Apply any corrected fields the doctor provided
    if payload.license_number:
        # Ensure no other doctor is already using the new license number
        existing = db.query(Doctor).filter(
            Doctor.license_number == payload.license_number,
            Doctor.id != doctor.id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="That license number is already registered to another account")
        doctor.license_number = payload.license_number

    if payload.mdcn_license_url:
        doctor.mdcn_license_url = payload.mdcn_license_url

    if payload.indemnity_cert_url:
        doctor.indemnity_cert_url = payload.indemnity_cert_url

    # Reset back to pending for admin re-review
    doctor.status = "pending"
    doctor.is_verified = False
    doctor.rejection_reason = None   # Clear the old rejection reason

    try:
        db.commit()
        db.refresh(doctor)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error during reapply: {e}")

    return doctor

@router.get("/", response_model=List[DoctorResponse])
def read_doctors(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    try:
        doctors = db.query(Doctor).filter(Doctor.is_verified == True).offset(skip).limit(limit).all()
        # Validate each doctor individually to find the bad record
        results = []
        for doc in doctors:
            try:
                results.append(DoctorResponse.model_validate(doc))
            except Exception as ve:
                print(f"🔥 [VALIDATION ERROR] Doctor ID={doc.id}, Name={doc.full_name}: {ve}")
                # Still include it with lenient fields
                results.append(DoctorResponse.model_validate(doc, strict=False))
        return results
    except Exception as e:
        import traceback
        print(f"🔥 [DOCTORS LIST ERROR] {e}")
        print(traceback.format_exc())
        raise

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
