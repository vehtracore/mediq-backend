
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import IntegrityError
from typing import List
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
import logging
import time
from app.core.database import get_db
from app.models.appointment import Appointment, DoctorSlot
from app.models.doctor import Doctor
from app.models.user import User
from app.models.review import Review
from app.models.vault import ConsultationRecord
from app.schemas.appointment import SlotCreate, SlotResponse, AppointmentCreate, AppointmentResponse, AppointmentUpdate, GeneralBookRequest, ReferralRequest, ReferralResponse, AppointmentProposeRequest, VIPBookRequest, ReferralCreate
from app.api import deps
from app.core.notifications import dispatch_push

logger = logging.getLogger(__name__)

router = APIRouter()

# --- Helper to build an AppointmentResponse, now including the
#     relational IDs that were previously missing from the schema.
def map_appt(a, doc_name=None, patient_name=None):
    d_name = doc_name if doc_name else (a.doctor.full_name if a.doctor else "Waiting...")

    # Guard slot access — slot may not be lazy-loaded in all contexts.
    # VIP requests have no slot, so start_time may be None.
    try:
        s_time = a.slot.start_time if (a.slot and a.slot_id) else getattr(a, 'start_time', None)
    except Exception:
        s_time = getattr(a, 'start_time', None)

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
        prescription=getattr(a, 'prescription', None),
    )


def _close_stale_patient_consultations(db: Session, patient_id: int) -> int:
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)
    stale_count = (
        db.query(Appointment)
        .filter(
            Appointment.patient_id == patient_id,
            Appointment.status == "confirmed",
            Appointment.start_time < cutoff,
        )
        .update({Appointment.status: "completed"}, synchronize_session=False)
    )

    db.commit()

    if stale_count:
        logger.info(
            "[APPT LAZY SWEEP] Closed %d stale confirmed consultation(s) for patient_id=%s.",
            stale_count,
            patient_id,
        )

    return stale_count


def _display_name(user: User | None) -> str:
    if not user:
        return "A patient"
    return f"{user.first_name or ''} {user.last_name or ''}".strip() or user.email or "A patient"


def _notify_user(
    user: User | None,
    *,
    title: str,
    body: str,
    notification_type: str,
    event_label: str,
    appointment_id: int | None = None,
):
    if not user:
        return

    data = {"type": notification_type}
    if appointment_id is not None:
        data["appointment_id"] = str(appointment_id)

    dispatch_push(
        token=user.fcm_token,
        title=title,
        body=body,
        data=data,
        event_label=event_label,
    )


def _notify_patient(
    db: Session,
    appt: Appointment,
    *,
    title: str,
    body: str,
    notification_type: str,
    event_label: str,
):
    patient = db.query(User).filter(User.id == appt.patient_id).first() if appt.patient_id else None
    _notify_user(
        patient,
        title=title,
        body=body,
        notification_type=notification_type,
        event_label=event_label,
        appointment_id=appt.id,
    )


def _notify_doctor(
    db: Session,
    doctor: Doctor | None,
    *,
    title: str,
    body: str,
    notification_type: str,
    event_label: str,
    appointment_id: int | None = None,
):
    doctor_user = db.query(User).filter(User.id == doctor.user_id).first() if doctor else None
    _notify_user(
        doctor_user,
        title=title,
        body=body,
        notification_type=notification_type,
        event_label=event_label,
        appointment_id=appointment_id,
    )

# ---------------------------------------------------------------------------
# Historical Context: Fetch the last 3 completed consultations for a patient
# ---------------------------------------------------------------------------
def _build_patient_history_context(
    db: Session,
    patient_id: int,
    *,
    exclude_appointment_id: int | None = None,
) -> str | None:
    """
    Queries the most recent 3 ConsultationRecords for *patient_id* from the
    Health Vault and compiles them into a human-readable text block that is
    appended to the notes the doctor sees.

    Returns ``None`` when there is no prior history (first-time patient).
    """
    query = (
        db.query(ConsultationRecord)
        .filter(ConsultationRecord.patient_id == patient_id)
    )
    if exclude_appointment_id is not None:
        query = query.filter(
            ConsultationRecord.appointment_id != exclude_appointment_id
        )
    records = (
        query
        .order_by(ConsultationRecord.created_at.desc())
        .limit(3)
        .all()
    )

    if not records:
        return None

    lines: list[str] = []
    lines.append("--- RECENT MEDICAL HISTORY (LAST 3 VISITS) ---")

    for idx, rec in enumerate(records, start=1):
        date_str = rec.created_at.strftime("%d %b %Y")

        # Resolve doctor name from the relationship
        doc_label = (
            f"Dr. {rec.doctor.full_name}" if rec.doctor else "Doctor"
        )

        # Build a brief one-liner summary from notes + prescriptions
        parts: list[str] = []
        if rec.clinical_notes:
            # Truncate long clinical notes to first 120 chars
            snippet = rec.clinical_notes[:120]
            if len(rec.clinical_notes) > 120:
                snippet += "…"
            parts.append(snippet)
        if rec.prescriptions:
            # prescriptions may be a JSON list or a plain string
            if isinstance(rec.prescriptions, list):
                rx_str = "; ".join(
                    f"{item.get('drug', '?')} {item.get('dosage', '')}".strip()
                    for item in rec.prescriptions
                )
            else:
                rx_str = str(rec.prescriptions)[:120]
            parts.append(f"Rx: {rx_str}")

        summary = " | ".join(parts) if parts else "No details recorded."
        lines.append(f"{idx}. [{date_str}] ({doc_label}): {summary}")

    return "\n".join(lines)


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

@router.delete("/slots/{slot_id}", status_code=200)
def delete_doctor_slot(
    slot_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """Delete an unbooked availability slot.

    Guardrails (in order):
      1. Slot must exist.
      2. Slot must belong to the authenticated doctor (ownership check).
      3. Slot must not be booked — booked slots must be cancelled via the
         appointment flow to preserve audit history.
    """
    slot = db.query(DoctorSlot).filter(DoctorSlot.id == slot_id).first()
    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found.")

    # Ownership: resolve doctor row from the authenticated user
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    if not doctor or slot.doctor_id != doctor.id:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to delete this slot.",
        )

    # Safety: refuse to delete a slot that already has a booking
    if slot.is_booked:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete a slot that is already booked. "
                   "Please cancel the appointment instead.",
        )

    db.delete(slot)
    db.commit()
    logger.info(
        "[Slot Delete] slot_id=%s deleted by doctor_id=%s (user_id=%s)",
        slot_id, doctor.id, current_user.id,
    )
    return {"status": "success", "message": f"Slot {slot_id} deleted."}

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
    patient_price = 4000.0
    platform_commission = round(patient_price * 0.30, 2)
    doctor_payout = round(patient_price - platform_commission, 2)
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


@router.post("/request", response_model=AppointmentResponse, status_code=status.HTTP_201_CREATED)
def request_vip_appointment(
    req: VIPBookRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """Creates a direct VIP request from a patient to a specific doctor.
    The appointment starts as pending/unpaid with no start_time, waiting
    for the doctor to propose a time via PATCH /propose.
    """
    # Verify the target doctor exists
    doctor = db.query(Doctor).filter(Doctor.id == req.doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    # ── VIP FEE FLOOR: default to ₦3,000 when doctor hasn't set a rate ────
    if not doctor.hourly_rate:
        doctor.hourly_rate = 3000

    # Guardrail: refuse VIP requests for doctors who haven't configured their rate.
    # This prevents ₦0 appointments and confusing zero-value Paystack checkouts.
    if not doctor.hourly_rate or doctor.hourly_rate <= 0:
        raise HTTPException(
            status_code=400,
            detail="Doctor has not set a consultation rate. Please try again later.",
        )

    # ── PENDING-LOCK: Rule 2 — Global cap (max 3 pending requests platform-wide) ──
    global_pending_count = (
        db.query(Appointment)
        .filter(
            Appointment.patient_id == current_user.id,
            Appointment.status == "pending",
        )
        .count()
    )
    if global_pending_count >= 3:
        raise HTTPException(
            status_code=400,
            detail="You have reached the maximum of 3 pending requests. "
                   "Please wait for a doctor to respond before sending more.",
        )

    # ── PENDING-LOCK: Rule 1 — Per-doctor cap (max 1 pending per specialist) ──
    per_doctor_pending_count = (
        db.query(Appointment)
        .filter(
            Appointment.patient_id == current_user.id,
            Appointment.doctor_id == req.doctor_id,
            Appointment.status == "pending",
        )
        .count()
    )
    if per_doctor_pending_count >= 1:
        raise HTTPException(
            status_code=400,
            detail="You already have a pending request with this specialist.",
        )

    # Pricing: derive from the doctor's actual rate, matching the /book endpoint
    # commission model (30% platform / 70% doctor payout).
    patient_price: float = doctor.hourly_rate
    commission: float = round(patient_price * 0.30, 2)
    doctor_payout: float = round(patient_price - commission, 2)

    logger.info(
        "[VIP Request] Pricing resolved — doctor_id=%s hourly_rate=%.2f "
        "patient_price=%.2f commission=%.2f payout=%.2f",
        doctor.id, doctor.hourly_rate or 0.0,
        patient_price, commission, doctor_payout,
    )

    new_appt = Appointment(
        patient_id=current_user.id,
        doctor_id=req.doctor_id,
        slot_id=None,
        start_time=None,       # No time yet — doctor will propose via /propose
        status="pending",
        payment_status="unpaid",
        notes=f"[{req.preferred_time}] {req.notes}",
        amount=patient_price,
        commission=commission,
        payout=doctor_payout,
    )
    db.add(new_appt)
    db.commit()
    db.refresh(new_appt)

    # Generate Paystack reference now so checkout is ready once doctor proposes time
    epoch_ms = int(time.time() * 1000)
    new_appt.paystack_reference = (
        f"MDQ-vip_request-{new_appt.id}-{current_user.id}-{epoch_ms}"
    )
    db.commit()

    # Re-fetch with relationships for map_appt
    new_appt = (
        db.query(Appointment)
        .options(
            joinedload(Appointment.doctor),
            joinedload(Appointment.review),
        )
        .filter(Appointment.id == new_appt.id)
        .first()
    )

    logger.info(
        "[VIP Request] patient_id=%s -> doctor_id=%s appt_id=%s",
        current_user.id, req.doctor_id, new_appt.id
    )
    _notify_doctor(
        db,
        doctor,
        title="VIP Request Received",
        body=f"{_display_name(current_user)} requested a VIP appointment.",
        notification_type="vip_request_received",
        event_label="APPOINTMENTS/VIP_REQUEST",
        appointment_id=new_appt.id,
    )
    return map_appt(new_appt)

@router.get("/my", response_model=List[AppointmentResponse])
def get_my_appointments(db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    _close_stale_patient_consultations(db, current_user.id)

    # Eager load review to avoid N+1
    scheduled = db.query(Appointment).options(joinedload(Appointment.review), joinedload(Appointment.slot)).join(DoctorSlot, Appointment.slot_id == DoctorSlot.id).filter(Appointment.patient_id == current_user.id).all()
    general = db.query(Appointment).options(joinedload(Appointment.review)).filter(Appointment.patient_id == current_user.id, Appointment.slot_id == None).all()
    results = [map_appt(a) for a in scheduled + general]
    results.sort(key=lambda x: x.start_time or datetime.min, reverse=True)
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
        .filter(
            Appointment.doctor_id == doctor.id,
            Appointment.status == "pending",
        )
        .all()
    )

    logger.info("[doctor/requests] Found %d pending request(s).", len(appts))

    # Pre-compute historical context per patient (cached per patient_id
    # within this request to avoid repeated DB round-trips).
    _history_cache: dict[int, str | None] = {}

    results = []
    for a in appts:
        p_name = f"{a.patient.first_name} {a.patient.last_name}" if a.patient else "Unknown"

        # Inject historical context into notes (doctor-side only)
        pid = a.patient_id
        if pid not in _history_cache:
            _history_cache[pid] = _build_patient_history_context(
                db, pid, exclude_appointment_id=a.id
            )
        enriched_notes = a.notes or ""
        if _history_cache[pid]:
            enriched_notes = f"{enriched_notes}\n\n{_history_cache[pid]}" if enriched_notes else _history_cache[pid]

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
            notes=enriched_notes,
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

    # SECURITY FIX: Only surface GP appointments to doctors after Paystack payment
    # is confirmed (payment_status == 'paid'). Unpaid GP bookings must NOT be
    # visible in the queue — the patient still needs to complete Paystack checkout.
    # NOTE: VIP appointments (doctor/requests) remain unpaid by design — the doctor
    # proposes a time BEFORE the patient pays, so that filter is intentionally absent there.
    appts = (
        db.query(Appointment)
        .options(joinedload(Appointment.patient))
        .filter(
            Appointment.doctor_id == None,  # noqa: E711
            Appointment.status == "pending",
            Appointment.payment_status == "paid",
        )
        .all()
    )

    logger.info("[doctor/queue] Found %d item(s) in general queue.", len(appts))

    # Pre-compute historical context per patient
    _history_cache: dict[int, str | None] = {}

    results = []
    for a in appts:
        p_name = f"{a.patient.first_name} {a.patient.last_name}" if a.patient else "Unknown"

        # Inject historical context into notes (doctor-side only)
        pid = a.patient_id
        if pid not in _history_cache:
            _history_cache[pid] = _build_patient_history_context(
                db, pid, exclude_appointment_id=a.id
            )
        enriched_notes = a.notes or ""
        if _history_cache[pid]:
            enriched_notes = f"{enriched_notes}\n\n{_history_cache[pid]}" if enriched_notes else _history_cache[pid]

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
            notes=enriched_notes,
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
    _notify_patient(
        db,
        appt,
        title="Appointment Confirmed",
        body="Your consultation has been confirmed.",
        notification_type="schedule_confirmed",
        event_label="APPOINTMENTS/QUEUE_CLAIMED",
    )
    return map_appt(appt, doctor.full_name)

@router.put("/doctor/appointments/{appt_id}/accept", response_model=AppointmentResponse)
def accept_appointment(appt_id: int, db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt: raise HTTPException(404)
    was_confirmed = appt.status == "confirmed"
    appt.status = "confirmed"
    db.commit()
    db.refresh(appt)
    if not was_confirmed:
        _notify_patient(
            db,
            appt,
            title="Appointment Confirmed",
            body="Your consultation has been confirmed.",
            notification_type="schedule_confirmed",
            event_label="APPOINTMENTS/ACCEPTED",
        )
    return map_appt(appt, doctor.full_name)

@router.put("/doctor/appointments/{appt_id}/decline", response_model=AppointmentResponse)
def decline_appointment(appt_id: int, db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt: raise HTTPException(404)
    was_cancelled = appt.status == "cancelled"
    appt.status = "cancelled"
    if appt.slot: appt.slot.is_booked = False
    db.commit()
    db.refresh(appt)
    if not was_cancelled:
        _notify_patient(
            db,
            appt,
            title="Appointment Cancelled",
            body="Your appointment request was declined.",
            notification_type="schedule_cancelled",
            event_label="APPOINTMENTS/DECLINED",
        )
    return map_appt(appt, doctor.full_name)

@router.put("/doctor/appointments/{appt_id}/cancel", response_model=AppointmentResponse)
def cancel_appointment_by_doctor(appt_id: int, db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt: raise HTTPException(404)
    was_cancelled = appt.status == "cancelled"
    appt.status = "cancelled"
    if appt.slot: appt.slot.is_booked = False
    db.commit()
    db.refresh(appt)
    if not was_cancelled:
        _notify_patient(
            db,
            appt,
            title="Appointment Cancelled",
            body="Your appointment was cancelled by the doctor.",
            notification_type="schedule_cancelled",
            event_label="APPOINTMENTS/CANCELLED_BY_DOCTOR",
        )
    return map_appt(appt, doctor.full_name)

@router.put("/doctor/appointments/{appt_id}/complete", response_model=AppointmentResponse)
def complete_appointment(appt_id: int, db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt: raise HTTPException(404)
    was_completed = appt.status == "completed"
    appt.status = "completed"

    # ── Compile referral data if the doctor issued a hospital referral ───
    referrals = (
        f"Referred to: {appt.referred_hospital}\nNote: {appt.referral_note}"
        if appt.referred_hospital
        else None
    )

    # ── Auto-create a ConsultationRecord in the Health Vault ─────────────
    # patient_id is sourced from the appointment row (NOT current_user,
    # which is the doctor) to guarantee correct ownership attribution.
    existing = (
        db.query(ConsultationRecord)
        .filter(ConsultationRecord.appointment_id == appt.id)
        .first()
    )
    if existing is None:
        vault_record = ConsultationRecord(
            appointment_id=appt.id,
            patient_id=appt.patient_id,
            doctor_id=doctor.id,
            clinical_notes=appt.notes,
            prescriptions=appt.prescription,
            referrals=referrals,
            created_at=datetime.now(timezone.utc),
        )
        db.add(vault_record)
        logger.info(
            "[Vault] ConsultationRecord created — appt_id=%s patient_id=%s doctor_id=%s prescription=%s referral=%s",
            appt.id, appt.patient_id, doctor.id,
            bool(appt.prescription), bool(referrals),
        )
    else:
        # Sync prescription and referral data into the existing vault record
        if appt.prescription:
            existing.prescriptions = appt.prescription
        if referrals:
            existing.referrals = referrals
        logger.info(
            "[Vault] ConsultationRecord updated — appt_id=%s prescription=%s referral=%s",
            appt.id, bool(appt.prescription), bool(referrals),
        )

    db.commit()
    db.refresh(appt)
    if not was_completed:
        _notify_patient(
            db,
            appt,
            title="Consultation Complete",
            body="Your consultation is complete. Any notes or prescriptions are available in your health vault.",
            notification_type="consultation_complete",
            event_label="APPOINTMENTS/COMPLETED",
        )
    return map_appt(appt, doctor.full_name)


# --- Doctor: Write/update a prescription for an appointment ---
@router.put("/doctor/appointments/{appt_id}/prescribe", response_model=AppointmentResponse)
def prescribe_appointment(
    appt_id: int,
    payload: AppointmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """
    Allows the assigned doctor to write or update a prescription / medication
    plan for a specific appointment. The prescription text is stored on the
    appointment row and propagated to the ConsultationRecord in the Health
    Vault the next time the appointment is completed.
    """
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    if not doctor:
        raise HTTPException(status_code=403, detail="Only doctors can prescribe.")

    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found.")
    if appt.doctor_id != doctor.id:
        raise HTTPException(status_code=403, detail="You are not the doctor for this appointment.")

    previous_prescription = appt.prescription
    prescription_added = False
    if payload.prescription is not None:
        appt.prescription = payload.prescription.strip() or None
        prescription_added = bool(appt.prescription) and appt.prescription != previous_prescription

    # If a ConsultationRecord already exists (appointment already completed),
    # update it immediately so the vault stays in sync.
    existing_record = (
        db.query(ConsultationRecord)
        .filter(ConsultationRecord.appointment_id == appt.id)
        .first()
    )
    if existing_record and appt.prescription:
        existing_record.prescriptions = appt.prescription

    db.commit()
    db.refresh(appt)

    logger.info(
        "[Prescribe] doctor_id=%s wrote prescription for appt_id=%s",
        doctor.id, appt.id,
    )
    if prescription_added:
        _notify_patient(
            db,
            appt,
            title="Prescription Added",
            body="Your doctor added a prescription to your consultation.",
            notification_type="prescription_added",
            event_label="APPOINTMENTS/PRESCRIPTION_ADDED",
        )
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

    # 5. Persist to appointment row — status intentionally NOT changed;
    #    the appointment remains "confirmed" until the doctor explicitly
    #    completes the session via the /complete endpoint.
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
    
    # Pre-compute historical context per patient
    _history_cache: dict[int, str | None] = {}

    results = []
    for a in scheduled + general:
        p_name = f"{a.patient.first_name} {a.patient.last_name}" if a.patient else "Unknown"
        start = a.slot.start_time if a.slot else a.start_time

        # Inject historical context into notes (doctor-side only)
        pid = a.patient_id
        if pid not in _history_cache:
            _history_cache[pid] = _build_patient_history_context(
                db, pid, exclude_appointment_id=a.id
            )
        enriched_notes = a.notes or ""
        if _history_cache[pid]:
            enriched_notes = f"{enriched_notes}\n\n{_history_cache[pid]}" if enriched_notes else _history_cache[pid]

        results.append(AppointmentResponse(
            id=a.id,
            doctor_id=a.doctor_id,
            patient_id=a.patient_id,
            doctor_name=p_name,      # repurposed: carries patient name for doctor-side view
            patient_name=p_name,
            status=a.status,
            payment_status=a.payment_status,
            is_acknowledged=getattr(a, 'is_acknowledged', False),
            start_time=start,
            notes=enriched_notes,
            has_review=False,
            amount=getattr(a, 'amount', 0.0),
            paystack_reference=getattr(a, 'paystack_reference', None),
        ))
    results.sort(key=lambda x: x.start_time or datetime.min)
    return results

@router.patch("/{appt_id}/acknowledge")
def acknowledge_appointment(appt_id: int, db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt:
        raise HTTPException(404, "Appointment not found")
    appt.is_acknowledged = True
    db.commit()
    return {"status": "success"}

@router.patch("/{appt_id}/propose", response_model=AppointmentResponse)
def propose_appointment_time(
    appt_id: int,
    payload: AppointmentProposeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user)
):
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt:
        raise HTTPException(404, "Appointment not found")

    # Guardrail: proposed time must not exceed 30 days from now.
    # Use UTC-aware comparison to avoid naive/aware datetime mixing.
    from datetime import timezone
    _max_date = datetime.now(timezone.utc) + timedelta(days=30)
    _proposed_utc = payload.proposed_time
    if _proposed_utc.tzinfo is None:
        # Treat naive datetimes (from older clients) as UTC
        _proposed_utc = _proposed_utc.replace(tzinfo=timezone.utc)
    if _proposed_utc > _max_date:
        raise HTTPException(
            status_code=400,
            detail="Proposed time cannot exceed 30 days from today.",
        )

    # Update start time and status
    appt.start_time = payload.proposed_time
    appt.status = "awaiting_payment"
    db.commit()
    db.refresh(appt)

    p_name = f"{appt.patient.first_name} {appt.patient.last_name}" if appt.patient else "Unknown"
    
    return AppointmentResponse(
        id=appt.id,
        doctor_id=appt.doctor_id,
        patient_id=appt.patient_id,
        doctor_name=p_name,
        patient_name=p_name,
        status=appt.status,
        payment_status=appt.payment_status,
        is_acknowledged=getattr(appt, 'is_acknowledged', False),
        start_time=appt.start_time,
        notes=appt.notes,
        has_review=False,
        amount=getattr(appt, 'amount', 0.0),
        paystack_reference=getattr(appt, 'paystack_reference', None)
    )


# ---------------------------------------------------------------------------
# POST /referral  — Clinical PDF Referral Generation + Email Dispatch
# ---------------------------------------------------------------------------

@router.post("/referral", status_code=200)
async def send_specialist_referral(
    payload: ReferralCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """
    POST /api/v1/appointments/referral

    Authenticated doctors only.  Generates a professional clinical referral
    PDF (via fpdf2) and emails it directly to a specialist or clinic using
    the Resend API with a base64-encoded attachment.

    Guards:
      1. Caller must be an active doctor (doctors row must exist).
      2. The referenced appointment must exist and belong to that doctor.

    Returns:
      200 {"status": "sent", "recipient": "...", "appointment_id": ...}
    """
    import base64
    import asyncio
    from fpdf import FPDF
    import resend as _resend
    import os

    # ── 1. Verify caller is a doctor ──────────────────────────────────────────
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    if not doctor:
        raise HTTPException(
            status_code=403,
            detail="Only verified doctors can issue clinical referrals.",
        )

    # ── 2. Fetch & verify appointment ownership ───────────────────────────────
    appt = (
        db.query(Appointment)
        .options(joinedload(Appointment.patient))
        .filter(Appointment.id == payload.appointment_id)
        .first()
    )
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found.")
    if appt.doctor_id != doctor.id:
        raise HTTPException(
            status_code=403,
            detail="You are not the doctor for this appointment.",
        )

    patient = appt.patient
    patient_name = (
        f"{patient.first_name} {patient.last_name}" if patient else "Unknown Patient"
    )
    today_str = datetime.utcnow().strftime("%d %B %Y")
    doctor_name = doctor.full_name

    # ── 3. Build PDF in memory ────────────────────────────────────────────────
    pdf = FPDF()
    pdf.set_margins(left=20, top=20, right=20)
    pdf.add_page()

    # Header bar
    pdf.set_fill_color(30, 115, 190)        # MDQ+ blue
    pdf.rect(0, 0, 210, 28, style="F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Arial", "B", 18)
    pdf.set_xy(20, 8)
    pdf.cell(0, 10, "MDQ+ Clinical Referral", ln=True)

    # Reset colour for body
    pdf.set_text_color(30, 30, 30)
    pdf.ln(12)

    # Meta block
    pdf.set_font("Arial", "", 11)
    pdf.cell(45, 7, "Date:", border=0)
    pdf.set_font("Arial", "B", 11)
    pdf.cell(0, 7, today_str, ln=True)

    pdf.set_font("Arial", "", 11)
    pdf.cell(45, 7, "Referring Doctor:", border=0)
    pdf.set_font("Arial", "B", 11)
    pdf.cell(0, 7, f"{doctor_name}  ({doctor.specialty})", ln=True)

    pdf.set_font("Arial", "", 11)
    pdf.cell(45, 7, "Patient:", border=0)
    pdf.set_font("Arial", "B", 11)
    pdf.cell(0, 7, patient_name, ln=True)

    pdf.set_font("Arial", "", 11)
    pdf.cell(45, 7, "Appointment Ref:", border=0)
    pdf.set_font("Arial", "B", 11)
    pdf.cell(0, 7, f"#{appt.id}", ln=True)

    pdf.ln(6)

    # Divider
    pdf.set_draw_color(180, 180, 180)
    pdf.line(20, pdf.get_y(), 190, pdf.get_y())
    pdf.ln(6)

    # Salutation
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 8, "To Whom It May Concern:", ln=True)
    pdf.ln(2)

    # Referral body
    pdf.set_font("Arial", "", 11)
    intro = (
        f"I am writing to refer {patient_name} for evaluation and management "
        f"by a {payload.specialist_type}. Please find the relevant clinical "
        f"information below."
    )
    pdf.multi_cell(0, 7, intro)
    pdf.ln(4)

    pdf.set_font("Arial", "B", 11)
    pdf.cell(0, 7, "Clinical Notes:", ln=True)
    pdf.set_font("Arial", "", 11)
    pdf.multi_cell(0, 7, payload.clinical_notes)
    pdf.ln(6)

    # Closing
    pdf.set_font("Arial", "", 11)
    pdf.multi_cell(
        0, 7,
        "Please do not hesitate to contact us should you require additional "
        "information regarding this patient.",
    )
    pdf.ln(8)
    pdf.set_font("Arial", "B", 11)
    pdf.cell(0, 7, f"Yours sincerely,", ln=True)
    pdf.ln(2)
    pdf.cell(0, 7, doctor_name, ln=True)
    pdf.set_font("Arial", "", 10)
    pdf.cell(0, 6, doctor.specialty, ln=True)
    pdf.cell(0, 6, "MDQ+ Telemedicine Platform", ln=True)

    # Footer watermark
    pdf.set_y(-18)
    pdf.set_font("Arial", "I", 8)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(
        0, 6,
        f"This referral was generated on {today_str} by MDQ+ | www.mdqplus.app",
        align="C",
    )

    # Serialise to bytes (fpdf2 returns bytearray from output())
    pdf_bytes: bytes = bytes(pdf.output())
    pdf_b64: str = base64.b64encode(pdf_bytes).decode("utf-8")

    # ── 4. Send email with PDF attachment via Resend ──────────────────────────
    resend_api_key: str = os.environ.get("RESEND_API_KEY", "")
    email_from: str = os.environ.get("EMAIL_FROM", "MDQ+ Health <noreply@mdqplus.app>")

    if not resend_api_key:
        logger.warning(
            "[REFERRAL] RESEND_API_KEY not set — PDF generated but email not sent "
            "(appointment_id=%s recipient=%s)",
            appt.id,
            payload.recipient_email,
        )
        return {
            "status": "pdf_generated_no_email",
            "detail": "RESEND_API_KEY not configured — email skipped.",
            "appointment_id": appt.id,
            "recipient": payload.recipient_email,
        }

    _resend.api_key = resend_api_key

    html_body = f"""
    <div style="font-family:sans-serif;max-width:560px;margin:auto;">
      <h2 style="color:#1E73BE;">Clinical Referral — MDQ+</h2>
      <p>Dear Specialist,</p>
      <p>
        Please find attached a clinical referral for
        <strong>{patient_name}</strong> from
        <strong>{doctor_name}</strong> ({doctor.specialty}).
      </p>
      <p>
        The referral has been issued for evaluation by a
        <strong>{payload.specialist_type}</strong>.
        Full clinical notes are contained in the attached PDF.
      </p>
      <p style="color:#555;font-size:13px;">— The MDQ+ Team | www.mdqplus.app</p>
    </div>
    """

    filename = f"MDQ_Referral_{patient_name.replace(' ', '_')}_{appt.id}.pdf"

    params: _resend.Emails.SendParams = {
        "from": email_from,
        "to": [payload.recipient_email],
        "subject": f"Clinical Referral for {patient_name} from MDQ+",
        "html": html_body,
        "attachments": [
            {
                "filename": filename,
                "content": pdf_b64,
            }
        ],
    }

    def _send_with_attachment() -> None:
        _resend.Emails.send(params)

    try:
        await asyncio.to_thread(_send_with_attachment)
        logger.info(
            "[REFERRAL] PDF referral emailed — appointment_id=%s recipient=%s",
            appt.id,
            payload.recipient_email,
        )
    except Exception as exc:
        logger.error(
            "[REFERRAL] Resend delivery failed — appointment_id=%s recipient=%s error=%s",
            appt.id,
            payload.recipient_email,
            exc,
        )
        raise HTTPException(
            status_code=502,
            detail=f"PDF generated but email delivery failed: {exc}",
        )

    return {
        "status": "sent",
        "recipient": payload.recipient_email,
        "appointment_id": appt.id,
        "patient_name": patient_name,
        "specialist_type": payload.specialist_type,
    }
