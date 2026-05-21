
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import IntegrityError
from typing import List
from datetime import datetime
from pydantic import BaseModel
import logging
import time
from app.core.database import get_db
from app.models.appointment import Appointment, DoctorSlot
from app.models.doctor import Doctor
from app.models.user import User
from app.models.review import Review
from app.schemas.appointment import SlotCreate, SlotResponse, AppointmentCreate, AppointmentResponse, GeneralBookRequest, ReferralRequest, ReferralResponse
from app.api import deps

logger = logging.getLogger(__name__)

router = APIRouter()

# --- Helper to build an AppointmentResponse, now including the
#     relational IDs that were previously missing from the schema.
def map_appt(a, doc_name=None, patient_name=None):
    d_name = doc_name if doc_name else (a.doctor.full_name if a.doctor else "Waiting...")

    # Guard slot access — slot may not be lazy-loaded in all contexts
    try:
        s_time = a.slot.start_time if a.slot else a.start_time
    except Exception:
        s_time = a.start_time

    # Resolve patient name from relationship if not supplied directly
    if patient_name is None and getattr(a, 'patient', None):
        patient_name = f"{a.patient.first_name} {a.patient.last_name}"

    has_rev = bool(getattr(a, 'review', None))

    logger.debug(
        "[map_appt] appt_id=%s doctor_id=%s patient_id=%s status=%s payment=%s",
        a.id,
        getattr(a, 'doctor_id', None),
        getattr(a, 'patient_id', None),
        a.status,
        a.payment_status,
    )

    return AppointmentResponse(
        id=a.id,
        doctor_id=getattr(a, 'doctor_id', None),
        patient_id=getattr(a, 'patient_id', None),
        doctor_name=d_name,
        patient_name=patient_name,
        status=a.status,
        payment_status=a.payment_status,
        is_acknowledged=getattr(a, 'is_acknowledged', False),
        start_time=s_time,
        notes=a.notes,
        amount=getattr(a, 'amount', 0.0),
        has_review=has_rev,
        paystack_reference=getattr(a, 'paystack_reference', None),
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
def book_appointment(
    appt_data: AppointmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    # --- Step 1: Fetch slot with its doctor eagerly to avoid lazy-load AttributeError ---
    slot = (
        db.query(DoctorSlot)
        .options(joinedload(DoctorSlot.doctor))
        .filter(DoctorSlot.id == appt_data.slot_id)
        .first()
    )

    # BUG FIX #1a: Explicit 404 for missing slot
    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found.")

    # BUG FIX #1b: Explicit 409 for already-booked slot
    if slot.is_booked:
        raise HTTPException(status_code=409, detail="This slot is already booked. Please choose another.")

    # BUG FIX #1c: Guard against a slot whose doctor row is missing (FK orphan)
    if not slot.doctor:
        logger.error("Data integrity issue: slot %s has no associated doctor.", slot.id)
        raise HTTPException(
            status_code=400,
            detail="This slot is misconfigured (no doctor assigned). Please contact support.",
        )

    # --- Step 2: Calculate financials ---
    amount: float = slot.doctor.hourly_rate or 0.0
    commission: float = round(amount * 0.30, 2)
    payout: float = round(amount - commission, 2)

    # --- Step 3: Mark slot as booked and create appointment ---
    slot.is_booked = True
    new_appt = Appointment(
        patient_id=current_user.id,
        doctor_id=slot.doctor_id,
        slot_id=slot.id,
        status="pending",
        payment_status="unpaid",
        notes=appt_data.notes,
        amount=amount,
        commission=commission,
        payout=payout,
    )
    db.add(new_appt)

    # BUG FIX #2: Catch IntegrityError from the UNIQUE constraint on slot_id
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        logger.warning("IntegrityError booking slot %s: %s", appt_data.slot_id, exc.orig)
        raise HTTPException(
            status_code=400,
            detail="This slot was just booked by another user. Please choose a different time.",
        ) from exc
    except Exception as exc:
        db.rollback()
        logger.exception("Unexpected error while booking appointment for user %s", current_user.id)
        raise HTTPException(
            status_code=500,
            detail="An unexpected server error occurred. Please try again later.",
        ) from exc

    # BUG FIX #3: Re-fetch with relationships eager-loaded so map_appt never triggers a lazy-load
    new_appt = (
        db.query(Appointment)
        .options(
            joinedload(Appointment.doctor),
            joinedload(Appointment.slot),
            joinedload(Appointment.review),
        )
        .filter(Appointment.id == new_appt.id)
        .first()
    )

    # ── Generate and persist the Paystack reference ────────────────────────
    # Done after first commit so we have the real appointment.id to embed.
    # Format: MDQ-{type}-{appointment_id}-{user_id}-{epoch_ms}
    epoch_ms = int(time.time() * 1000)
    new_appt.paystack_reference = (
        f"MDQ-specialist_consult-{new_appt.id}-{current_user.id}-{epoch_ms}"
    )
    db.commit()
    db.refresh(new_appt)

    return map_appt(new_appt)

@router.post("/book-general", response_model=AppointmentResponse, status_code=status.HTTP_201_CREATED)
def book_general_consultation(req: GeneralBookRequest, db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    doctor_payout = 1750.0
    patient_price = 2500.0 if current_user.plan == "premium" else 4000.0
    platform_commission = patient_price - doctor_payout
    new_appointment = Appointment(
        patient_id=current_user.id, doctor_id=None, slot_id=None,
        start_time=datetime.utcnow(), status="pending", payment_status="unpaid",
        notes=req.notes, amount=patient_price,
        commission=platform_commission, payout=doctor_payout,
    )
    db.add(new_appointment)
    db.commit()
    db.refresh(new_appointment)

    # ── Generate and persist the Paystack reference ────────────────────────
    epoch_ms = int(time.time() * 1000)
    new_appointment.paystack_reference = (
        f"MDQ-gp_consult-{new_appointment.id}-{current_user.id}-{epoch_ms}"
    )
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
    if not doctor:
        logger.warning("[doctor/requests] No doctor row for user_id=%s", current_user.id)
        raise HTTPException(403, "Not a doctor")

    logger.info(
        "[doctor/requests] Fetching pending requests for doctor_id=%s user_id=%s",
        doctor.id, current_user.id,
    )

    # NOTE: We intentionally include BOTH 'paid' and 'unpaid' pending appointments
    # so the list is visible to doctors even before Paystack webhook fires.
    # Tighten this back to payment_status=="paid" once webhooks are confirmed working.
    appts = (
        db.query(Appointment)
        .options(joinedload(Appointment.patient), joinedload(Appointment.slot))
        .join(DoctorSlot)
        .filter(
            Appointment.doctor_id == doctor.id,
            Appointment.status == "pending",
        )
        .all()
    )

    logger.info("[doctor/requests] Found %d pending request(s).", len(appts))

    results = []
    for a in appts:
        p_name = f"{a.patient.first_name} {a.patient.last_name}" if a.patient else "Unknown"
        # doctor_name field repurposed to carry patient name in doctor-side view
        results.append(AppointmentResponse(
            id=a.id,
            doctor_id=a.doctor_id,
            patient_id=a.patient_id,
            doctor_name=p_name,        # shown as "patient" on doctor's UI
            patient_name=p_name,
            status=a.status,
            payment_status=a.payment_status,
            is_acknowledged=getattr(a, 'is_acknowledged', False),
            start_time=a.slot.start_time if a.slot else a.start_time,
            notes=a.notes,
            has_review=False,
            amount=getattr(a, 'amount', 0.0),
        ))
    return results

@router.get("/doctor/queue", response_model=List[AppointmentResponse])
def get_general_queue(db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    if not doctor:
        logger.warning("[doctor/queue] No doctor row for user_id=%s", current_user.id)
        raise HTTPException(403, "Not a doctor")

    logger.info(
        "[doctor/queue] Fetching general queue for doctor_id=%s user_id=%s",
        doctor.id, current_user.id,
    )

    # NOTE: payment_status filter removed temporarily to surface all pending GP
    # consultations regardless of Paystack webhook status. Re-add once webhooks confirmed.
    appts = (
        db.query(Appointment)
        .options(joinedload(Appointment.patient))
        .filter(
            Appointment.doctor_id == None,  # noqa: E711
            Appointment.status == "pending",
        )
        .all()
    )

    logger.info("[doctor/queue] Found %d item(s) in general queue.", len(appts))

    results = []
    for a in appts:
        p_name = f"{a.patient.first_name} {a.patient.last_name}" if a.patient else "Unknown"
        results.append(AppointmentResponse(
            id=a.id,
            doctor_id=a.doctor_id,
            patient_id=a.patient_id,
            doctor_name=p_name,      # shown as "patient" on doctor's UI
            patient_name=p_name,
            status=a.status,
            payment_status=a.payment_status,
            is_acknowledged=getattr(a, 'is_acknowledged', False),
            start_time=a.start_time,
            notes=a.notes,
            has_review=False,
            amount=getattr(a, 'amount', 0.0),
        ))
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


# --- Continuity of Care: Physical Hospital Referral ---
@router.post("/doctor/appointments/{appt_id}/refer", response_model=ReferralResponse)
def refer_patient_to_hospital(
    appt_id: int,
    referral: ReferralRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """
    Allows an authenticated doctor to refer a patient to a physical hospital.
    Generates a standardised referral note and persists it against the appointment.
    """
    # 1. Guard — must be a doctor
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    if not doctor:
        raise HTTPException(status_code=403, detail="Only doctors can issue referrals.")

    # 2. Fetch appointment and verify ownership
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found.")
    if appt.doctor_id != doctor.id:
        raise HTTPException(status_code=403, detail="You are not the doctor for this appointment.")

    # 3. Resolve patient name
    patient = appt.patient
    patient_name = f"{patient.first_name} {patient.last_name}" if patient else "Unknown Patient"

    # 4. Build standardised referral string
    slot_time = appt.slot.start_time if appt.slot else appt.start_time
    referral_note = (
        f"REFERRAL — MDQ+ Platform\n"
        f"Date: {datetime.utcnow().strftime('%d %b %Y, %H:%M')} UTC\n"
        f"Referring Doctor: Dr. {doctor.full_name} ({doctor.specialty})\n"
        f"Patient: {patient_name}\n"
        f"Original Appointment: #{appt.id} on {slot_time.strftime('%d %b %Y') if slot_time else 'N/A'}\n"
        f"Referred To: {referral.hospital_name}\n"
        f"Clinical Note: {referral.note}"
    )

    # 5. Persist to appointment row
    appt.status = "referred"
    appt.referred_hospital = referral.hospital_name
    appt.referral_note = referral_note
    db.commit()
    db.refresh(appt)

    # 6. Return enriched response
    base = map_appt(appt, doctor.full_name)
    return ReferralResponse(
        **base.model_dump(),
        referred_hospital=appt.referred_hospital,
        referral_note=appt.referral_note,
    )

@router.get("/doctor/appointments", response_model=List[AppointmentResponse])
def get_doctor_confirmed_appointments(db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    scheduled = db.query(Appointment).options(joinedload(Appointment.patient), joinedload(Appointment.slot)).join(DoctorSlot, Appointment.slot_id == DoctorSlot.id).filter(Appointment.doctor_id == doctor.id, Appointment.status == "confirmed").all()
    general = db.query(Appointment).options(joinedload(Appointment.patient)).filter(Appointment.doctor_id == doctor.id, Appointment.slot_id == None, Appointment.status == "confirmed").all()
    
    results = []
    for a in scheduled + general:
        p_name = f"{a.patient.first_name} {a.patient.last_name}" if a.patient else "Unknown"
        start = a.slot.start_time if a.slot else a.start_time
        results.append(AppointmentResponse(id=a.id, doctor_name=p_name, status=a.status, payment_status=a.payment_status, is_acknowledged=getattr(a, 'is_acknowledged', False), start_time=start, notes=a.notes, has_review=False))
    results.sort(key=lambda x: x.start_time)
    return results

@router.patch("/{appt_id}/acknowledge")
def acknowledge_appointment(appt_id: int, db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt:
        raise HTTPException(404, "Appointment not found")
    appt.is_acknowledged = True
    db.commit()
    return {"status": "success"}
