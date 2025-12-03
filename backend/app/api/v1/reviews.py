from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.core.database import get_db
from app.models.review import Review
from app.models.appointment import Appointment
from app.models.doctor import Doctor
from app.models.user import User
from app.schemas.review import ReviewCreate, ReviewResponse
from app.api import deps

router = APIRouter()

@router.post("/", response_model=ReviewResponse, status_code=status.HTTP_201_CREATED)
def create_review(
    review_in: ReviewCreate, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(deps.get_current_user)):
    
    # 1. Verify Appointment exists and is completed
    appointment = db.query(Appointment).filter(Appointment.id == review_in.appointment_id).first()
    if not appointment: raise HTTPException(404, detail="Appointment not found")
    
    # 2. Verify Permission
    if appointment.patient_id != current_user.id: raise HTTPException(403, detail="Not authorized")
    if appointment.status != "completed": raise HTTPException(400, detail="Can only review completed appointments")
    
    # 3. Check for duplicates
    if db.query(Review).filter(Review.appointment_id == review_in.appointment_id).first():
        raise HTTPException(400, detail="You have already reviewed this appointment")

    # 4. Save Review
    new_review = Review(
        appointment_id=review_in.appointment_id,
        doctor_id=appointment.doctor_id,
        patient_id=current_user.id,
        rating=review_in.rating,
        comment=review_in.comment
    )
    db.add(new_review)
    db.commit()

    # 5. AUTO-CALCULATE DOCTOR RATING
    if appointment.doctor_id:
        doctor = db.query(Doctor).filter(Doctor.id == appointment.doctor_id).first()
        if doctor:
            stats = db.query(func.avg(Review.rating), func.count(Review.id)).filter(Review.doctor_id == doctor.id).first()
            if stats[0]:
                doctor.rating = round(stats[0], 1)
                doctor.review_count = stats[1]
                db.add(doctor)
                db.commit()

    db.refresh(new_review)
    return new_review