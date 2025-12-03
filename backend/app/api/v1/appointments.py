
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from typing import List
from datetime import datetime
from pydantic import BaseModel
from app.core.database import get_db
from app.models.appointment import Appointment, DoctorSlot
from app.models.doctor import Doctor
from app.models.user import User
from app.models.review import Review
from app.schemas.appointment import SlotCreate, SlotResponse, AppointmentCreate, AppointmentResponse, GeneralBookRequest
from app.api import deps

router = APIRouter()

# ... (Helper to Map Response) ...
def map_appt(a, doc_name=None):
    d_name = doc_name if doc_name else (a.doctor.full_name if a.doctor else "Waiting...")
    s_time = a.slot.start_time if a.slot else a.start_time
    # CHECK IF REVIEW EXISTS
    has_rev = True if a.review else False
    return AppointmentResponse(
        id=a.id, doctor_name=d_name, status=a.status, 
        payment_status=a.payment_status, start_time=s_time, 
        notes=a.notes, amount=a.amount, has_review=has_rev
    )

# ... (Slots & Booking - Standard) ...
@router.post("/slots", response_model=SlotResponse, status_code=status.HTTP_201_CREATED)
def create_slot(slot: SlotCreate, db: Session = Depends(get_db)):
    doctor = db.query(Doctor).filter(Doctor.id == slot.doctor_id).first()
    if not doctor: raise HTTPException(404, "Doctor not found")
    new_slot = DoctorSlot(doctor_id=slot.doctor_id, start_time=slot.start_time, is_booked=False)
    db.add(new_slot)
    db.commit()
    db.refresh(new_slot)
    return new_slot

@router.get("/doctors/{doctor_id}/slots", response_model=List[SlotResponse])
def get_doctor_slots(doctor_id: int, db: Session = Depends(get_db)):
    return db.query(DoctorSlot).filter(DoctorSlot.doctor_id == doctor_id, DoctorSlot.is_booked == False).order_by(DoctorSlot.start_time).all()

@router.post("/book", response_model=AppointmentResponse, status_code=status.HTTP_201_CREATED)
def book_appointment(appt_data: AppointmentCreate, db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    slot = db.query(DoctorSlot).filter(DoctorSlot.id == appt_data.slot_id).first()
    if not slot or slot.is_booked: raise HTTPException(400, "Slot unavailable")
    slot.is_booked = True
    amount = slot.doctor.hourly_rate
    commission = amount * 0.30
    payout = amount - commission
    new_appt = Appointment(patient_id=current_user.id, doctor_id=slot.doctor_id, slot_id=slot.id, status="pending", payment_status="unpaid", notes=appt_data.notes, amount=amount, commission=commission, payout=payout)
    db.add(new_appt)
    db.commit()
    db.refresh(new_appt)
    return map_appt(new_appt)

@router.post("/book-general", response_model=AppointmentResponse, status_code=status.HTTP_201_CREATED)
def book_general_consultation(req: GeneralBookRequest, db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    doctor_payout = 1750.0
    patient_price = 2500.0 if current_user.plan == "premium" else 4000.0
    platform_commission = patient_price - doctor_payout
    new_appointment = Appointment(patient_id=current_user.id, doctor_id=None, slot_id=None, start_time=datetime.utcnow(), status="pending", payment_status="unpaid", notes=req.notes, amount=patient_price, commission=platform_commission, payout=doctor_payout)
    db.add(new_appointment)
    db.commit()
    db.refresh(new_appointment)
    return map_appt(new_appointment, "General Practitioner")

@router.get("/my", response_model=List[AppointmentResponse])
def get_my_appointments(db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    # Eager load review to avoid N+1
    scheduled = db.query(Appointment).options(joinedload(Appointment.review), joinedload(Appointment.slot)).join(DoctorSlot, Appointment.slot_id == DoctorSlot.id).filter(Appointment.patient_id == current_user.id).all()
    general = db.query(Appointment).options(joinedload(Appointment.review)).filter(Appointment.patient_id == current_user.id, Appointment.slot_id == None).all()
    results = [map_appt(a) for a in scheduled + general]
    results.sort(key=lambda x: x.start_time, reverse=True)
    return results

@router.put("/{appt_id}/pay", response_model=AppointmentResponse)
def pay_appointment(appt_id: int, db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt: raise HTTPException(404, "Not found")
    appt.payment_status = "paid"
    db.commit()
    db.refresh(appt)
    return map_appt(appt)

@router.put("/{appt_id}/cancel", response_model=AppointmentResponse)
def cancel_my_appointment(appt_id: int, db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt: raise HTTPException(404, "Not found")
    appt.status = "cancelled"
    if appt.slot: appt.slot.is_booked = False
    db.commit()
    db.refresh(appt)
    return map_appt(appt)

# --- DOCTOR ENDPOINTS ---
@router.get("/doctor/requests", response_model=List[AppointmentResponse])
def get_doctor_requests(db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    if not doctor: raise HTTPException(403, "Not a doctor")
    appts = db.query(Appointment).options(joinedload(Appointment.patient)).join(DoctorSlot).filter(Appointment.doctor_id == doctor.id, Appointment.status == "pending", Appointment.payment_status == "paid").all()
    results = []
    for a in appts:
        a.patient_name = f"{a.patient.first_name} {a.patient.last_name}" if a.patient else "Unknown"
        results.append(AppointmentResponse(id=a.id, doctor_name=a.patient_name, status=a.status, payment_status=a.payment_status, start_time=a.slot.start_time, notes=a.notes, has_review=False))
    return results

@router.get("/doctor/queue", response_model=List[AppointmentResponse])
def get_general_queue(db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    if not doctor: raise HTTPException(403)
    appts = db.query(Appointment).options(joinedload(Appointment.patient)).filter(Appointment.doctor_id == None, Appointment.status == "pending", Appointment.payment_status == "paid").all()
    results = []
    for a in appts:
        # doctor_name field used for Patient Name in Doctor View
        p_name = f"{a.patient.first_name} {a.patient.last_name}" if a.patient else "Unknown"
        results.append(AppointmentResponse(id=a.id, doctor_name=p_name, status=a.status, payment_status=a.payment_status, start_time=a.start_time, notes=a.notes, has_review=False))
    return results

@router.put("/doctor/queue/{appt_id}/claim", response_model=AppointmentResponse)
def claim_appointment(appt_id: int, db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    appt = db.query(Appointment).filter(Appointment.id == appt_id, Appointment.doctor_id == None).first()
    if not appt: raise HTTPException(404)
    appt.doctor_id = doctor.id
    appt.status = "confirmed"
    db.commit()
    db.refresh(appt)
    return map_appt(appt, doctor.full_name)

@router.put("/doctor/appointments/{appt_id}/accept", response_model=AppointmentResponse)
def accept_appointment(appt_id: int, db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt: raise HTTPException(404)
    appt.status = "confirmed"
    db.commit()
    db.refresh(appt)
    return map_appt(appt, doctor.full_name)

@router.put("/doctor/appointments/{appt_id}/decline", response_model=AppointmentResponse)
def decline_appointment(appt_id: int, db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt: raise HTTPException(404)
    appt.status = "cancelled"
    if appt.slot: appt.slot.is_booked = False
    db.commit()
    db.refresh(appt)
    return map_appt(appt, doctor.full_name)

@router.put("/doctor/appointments/{appt_id}/cancel", response_model=AppointmentResponse)
def cancel_appointment_by_doctor(appt_id: int, db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt: raise HTTPException(404)
    appt.status = "cancelled"
    if appt.slot: appt.slot.is_booked = False
    db.commit()
    db.refresh(appt)
    return map_appt(appt, doctor.full_name)

@router.put("/doctor/appointments/{appt_id}/complete", response_model=AppointmentResponse)
def complete_appointment(appt_id: int, db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt: raise HTTPException(404)
    appt.status = "completed"
    db.commit()
    db.refresh(appt)
    return map_appt(appt, doctor.full_name)

@router.get("/doctor/appointments", response_model=List[AppointmentResponse])
def get_doctor_confirmed_appointments(db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    scheduled = db.query(Appointment).options(joinedload(Appointment.patient), joinedload(Appointment.slot)).join(DoctorSlot, Appointment.slot_id == DoctorSlot.id).filter(Appointment.doctor_id == doctor.id, Appointment.status == "confirmed").all()
    general = db.query(Appointment).options(joinedload(Appointment.patient)).filter(Appointment.doctor_id == doctor.id, Appointment.slot_id == None, Appointment.status == "confirmed").all()
    
    results = []
    for a in scheduled + general:
        p_name = f"{a.patient.first_name} {a.patient.last_name}" if a.patient else "Unknown"
        start = a.slot.start_time if a.slot else a.start_time
        results.append(AppointmentResponse(id=a.id, doctor_name=p_name, status=a.status, payment_status=a.payment_status, start_time=start, notes=a.notes, has_review=False))
    results.sort(key=lambda x: x.start_time)
    return results
