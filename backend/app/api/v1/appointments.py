
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import IntegrityError
from typing import List
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
import logging
import time
from app.core.database import get_db
from app.models.appointment import (
    APPOINTMENT_TYPE_GENERAL_QUEUE,
    APPOINTMENT_TYPE_SPECIALIST_SCHEDULED,
    APPOINTMENT_TYPE_VIP_REQUEST,
    Appointment,
    DoctorSlot,
    appointment_start_utc,
    as_naive_utc,
    resolve_appointment_type,
)
from app.models.doctor import Doctor
from app.models.user import User
from app.models.review import Review
from app.models.vault import ConsultationRecord
from app.schemas.appointment import SlotCreate, SlotResponse, AppointmentCreate, AppointmentResponse, AppointmentUpdate, GeneralBookRequest, ReferralRequest, ReferralResponse, AppointmentProposeRequest, VIPBookRequest, ReferralCreate
from app.services.consultation_pricing import (
    CONSULTATION_ROOM_EARLY_ACCESS_MINUTES,
    calculate_consultation_split,
)
from app.services.consultation_completion import complete_consultation
from app.services.consultation_payout_service import consultation_payout_hold_until
from app.services.consultation_refund_service import REFUND_STATUS_AWAITING_ADMIN
from app.api import deps
from app.core.notifications import dispatch_push

logger = logging.getLogger(__name__)

router = APIRouter()


class AppointmentComplaintRequest(BaseModel):
    reason: str


# ---------------------------------------------------------------------------
# Appointment authorization helpers
# ---------------------------------------------------------------------------

def consultation_has_opened(appointment: Appointment) -> bool:
    """Return true once cancellation must give way to attendance/no-show logic."""
    if getattr(appointment, "consultation_started_at", None) is not None:
        return True

    scheduled_start = appointment_start_utc(appointment)
    if scheduled_start is None:
        return False

    appointment_type = resolve_appointment_type(appointment)
    if appointment_type in {
        APPOINTMENT_TYPE_SPECIALIST_SCHEDULED,
        APPOINTMENT_TYPE_VIP_REQUEST,
    }:
        opens_at = scheduled_start - timedelta(
            minutes=CONSULTATION_ROOM_EARLY_ACCESS_MINUTES
        )
    else:
        opens_at = scheduled_start

    return datetime.now(timezone.utc) >= opens_at


def require_patient_role(current_user: User) -> User:
    """Require an active patient account."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive accounts cannot perform patient appointment actions.",
        )
    if current_user.role != "patient":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only patients can perform this appointment action.",
        )
    return current_user


def require_approved_doctor(current_user: User, db: Session) -> Doctor:
    """Resolve a doctor whose account passed the active-account approval gate."""
    if not current_user.is_active or current_user.role != "doctor":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only active doctors can perform this appointment action.",
        )

    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Doctor profile not found.",
        )
    return doctor


def require_patient_owner(
    appointment: Appointment,
    current_user: User,
) -> Appointment:
    """Require the authenticated patient to own the appointment."""
    require_patient_role(current_user)
    if appointment.patient_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this appointment.",
        )
    return appointment


def require_assigned_doctor(
    appointment: Appointment,
    current_user: User,
    db: Session,
) -> Doctor:
    """Require the approved caller to be the appointment's assigned doctor."""
    doctor = require_approved_doctor(current_user, db)
    if appointment.doctor_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This appointment has not been assigned to a doctor.",
        )
    if appointment.doctor_id != doctor.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not the assigned doctor for this appointment.",
        )
    return doctor


def require_patient_or_assigned_doctor(
    appointment: Appointment,
    current_user: User,
    db: Session,
) -> Doctor | None:
    """Allow only the owning patient or the assigned approved doctor."""
    if current_user.role == "patient":
        require_patient_owner(appointment, current_user)
        return None
    if current_user.role == "doctor":
        return require_assigned_doctor(appointment, current_user, db)
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to access this appointment.",
    )


def require_general_queue_claimable(
    appointment: Appointment,
) -> Appointment:
    """Require an appointment to be eligible for a general-queue claim."""
    if resolve_appointment_type(appointment) != APPOINTMENT_TYPE_GENERAL_QUEUE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only general queue appointments can be claimed.",
        )
    if appointment.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only pending appointments can be claimed.",
        )
    if appointment.payment_status != "paid":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The appointment must be paid before it can be claimed.",
        )
    if appointment.doctor_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This appointment has already been claimed.",
        )
    if appointment.slot_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Slot-based appointments cannot be claimed from the general queue.",
        )
    return appointment


def require_vip_requested_doctor(
    appointment: Appointment,
    current_user: User,
    db: Session,
) -> Doctor:
    """Require the caller to be the doctor explicitly requested for a VIP flow."""
    doctor = require_approved_doctor(current_user, db)
    if resolve_appointment_type(appointment) != APPOINTMENT_TYPE_VIP_REQUEST:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This action is only valid for VIP doctor requests.",
        )
    if appointment.doctor_id != doctor.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the requested VIP doctor can perform this action.",
        )
    return doctor


def require_slot_owner(
    slot: DoctorSlot,
    current_user: User,
    db: Session,
) -> Doctor:
    """Require the caller to own the slot, with explicit admin delegation."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive accounts cannot manage doctor slots.",
        )

    if current_user.role == "admin":
        slot_doctor = db.query(Doctor).filter(Doctor.id == slot.doctor_id).first()
        if not slot_doctor:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="The doctor assigned to this slot was not found.",
            )
        return slot_doctor

    doctor = require_approved_doctor(current_user, db)
    if slot.doctor_id != doctor.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to manage another doctor's slot.",
        )
    return doctor


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
        appointment_type=resolve_appointment_type(a),
        doctor_name=d_name,
        patient_name=patient_name,
        status=a.status,
        payment_status=a.payment_status,
        is_acknowledged=getattr(a, 'is_acknowledged', False),
        start_time=s_time,
        patient_joined_at=getattr(a, 'patient_joined_at', None),
        doctor_joined_at=getattr(a, 'doctor_joined_at', None),
        consultation_started_at=getattr(a, 'consultation_started_at', None),
        no_show_marked_at=getattr(a, 'no_show_marked_at', None),
        refund_status=getattr(a, 'refund_status', None),
        refund_reference=getattr(a, 'refund_reference', None),
        refund_amount=getattr(a, 'refund_amount', None),
        refund_processed_at=getattr(a, 'refund_processed_at', None),
        notes=a.notes,
        amount=getattr(a, 'amount', 0.0),
        has_review=has_rev,
        paystack_reference=getattr(a, 'paystack_reference', None),
        prescription=getattr(a, 'prescription', None),
    )


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
def create_slot(
    slot: SlotCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    doctor = db.query(Doctor).filter(Doctor.id == slot.doctor_id).first()
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor not found.",
        )

    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive accounts cannot create doctor slots.",
        )

    if current_user.role == "admin":
        # Admins may create a slot on behalf of a doctor whose account has
        # passed the same active-account approval gate.
        doctor_user = (
            db.query(User).filter(User.id == doctor.user_id).first()
            if doctor.user_id
            else None
        )
        if doctor_user is None or not doctor_user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Slots can only be created for active doctor accounts.",
            )
    else:
        current_doctor = require_approved_doctor(current_user, db)
        if current_doctor.id != doctor.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot create a slot for another doctor.",
            )

    new_slot = DoctorSlot(
        doctor_id=slot.doctor_id,
        start_time=as_naive_utc(slot.start_time),
        is_booked=False,
    )
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
    require_patient_role(current_user)

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

    doctor_user = (
        db.query(User).filter(User.id == slot.doctor.user_id).first()
        if slot.doctor.user_id
        else None
    )
    if doctor_user is None or not doctor_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This specialist is not currently available for booking.",
        )

    slot_start = slot.start_time
    if slot_start is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This appointment slot is missing a valid start time.",
        )
    now_utc = datetime.now(timezone.utc)
    if slot_start.tzinfo is None:
        slot_start = slot_start.replace(tzinfo=timezone.utc)
    else:
        slot_start = slot_start.astimezone(timezone.utc)
    if slot_start <= now_utc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This appointment slot is no longer available.",
        )

    # --- Step 2: Calculate financials ---
    amount: float = (
        slot.doctor.consultation_fee
        or slot.doctor.hourly_rate
        or 0.0
    )
    commission, payout = calculate_consultation_split(amount)

    # --- Step 3: Mark slot as booked and create appointment ---
    slot.is_booked = True
    new_appt = Appointment(
        patient_id=current_user.id,
        doctor_id=slot.doctor_id,
        slot_id=slot.id,
        appointment_type=APPOINTMENT_TYPE_SPECIALIST_SCHEDULED,
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
            status_code=status.HTTP_409_CONFLICT,
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

    # TODO: Add a scheduled expiry/release process for unpaid specialist
    # reservations so abandoned checkouts do not hold slots indefinitely.
    return map_appt(new_appt)

@router.post("/book-general", response_model=AppointmentResponse, status_code=status.HTTP_201_CREATED)
def book_general_consultation(req: GeneralBookRequest, db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    patient_price = 4000.0
    platform_commission, doctor_payout = calculate_consultation_split(
        patient_price
    )
    new_appointment = Appointment(
        patient_id=current_user.id, doctor_id=None, slot_id=None,
        appointment_type=APPOINTMENT_TYPE_GENERAL_QUEUE,
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
    require_patient_role(current_user)

    # Verify the target doctor exists
    doctor = db.query(Doctor).filter(Doctor.id == req.doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    if (
        doctor.status != "active"
        or doctor.user is None
        or not doctor.user.is_active
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This doctor is not currently accepting appointment requests.",
        )

    # Guardrail: refuse VIP requests for doctors who haven't configured their rate.
    # This prevents ₦0 appointments and confusing zero-value Paystack checkouts.
    consultation_fee = doctor.consultation_fee or doctor.hourly_rate or 0.0
    if consultation_fee < 4000:
        raise HTTPException(
            status_code=400,
            detail="Doctor has not set a valid consultation rate. Please try again later.",
        )

    # ── PENDING-LOCK: Rule 2 — Global cap (max 3 pending requests platform-wide) ──
    existing_request = (
        db.query(Appointment)
        .options(
            joinedload(Appointment.doctor),
            joinedload(Appointment.review),
        )
        .filter(
            Appointment.patient_id == current_user.id,
            Appointment.doctor_id == req.doctor_id,
            Appointment.appointment_type == APPOINTMENT_TYPE_VIP_REQUEST,
            Appointment.status.in_(("pending", "awaiting_payment")),
        )
        .first()
    )
    if existing_request is not None:
        return map_appt(existing_request)

    global_pending_count = (
        db.query(Appointment)
        .filter(
            Appointment.patient_id == current_user.id,
            Appointment.appointment_type == APPOINTMENT_TYPE_VIP_REQUEST,
            Appointment.status.in_(("pending", "awaiting_payment")),
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
    # Pricing: derive from the doctor's actual rate using the central split rule.
    patient_price: float = consultation_fee
    commission, doctor_payout = calculate_consultation_split(patient_price)

    logger.info(
        "[VIP Request] Pricing resolved — doctor_id=%s consultation_fee=%.2f "
        "patient_price=%.2f commission=%.2f payout=%.2f",
        doctor.id, consultation_fee,
        patient_price, commission, doctor_payout,
    )

    new_appt = Appointment(
        patient_id=current_user.id,
        doctor_id=req.doctor_id,
        slot_id=None,
        appointment_type=APPOINTMENT_TYPE_VIP_REQUEST,
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
    # Preserve the existing scheduled/general split and response ordering.
    # Eager-load every relationship touched by map_appt so this endpoint does
    # not issue one extra doctor-profile query per appointment.
    scheduled = (
        db.query(Appointment)
        .options(
            joinedload(Appointment.doctor).load_only(Doctor.id, Doctor.full_name),
            joinedload(Appointment.review),
            joinedload(Appointment.slot),
        )
        .join(DoctorSlot, Appointment.slot_id == DoctorSlot.id)
        .filter(Appointment.patient_id == current_user.id)
        .all()
    )
    general = (
        db.query(Appointment)
        .options(
            joinedload(Appointment.doctor).load_only(Doctor.id, Doctor.full_name),
            joinedload(Appointment.review),
        )
        .filter(
            Appointment.patient_id == current_user.id,
            Appointment.slot_id == None,  # noqa: E711
        )
        .all()
    )
    results = [map_appt(a) for a in scheduled + general]
    results.sort(key=lambda x: x.start_time or datetime.min, reverse=True)
    return results

@router.put("/{appt_id}/pay", status_code=status.HTTP_410_GONE)
def pay_appointment(
    appt_id: int,
    current_user: User = Depends(deps.get_current_user),
):
    """Deprecated manual payment mutation.

    Appointment payment state must only be changed after server-side payment
    provider verification. The route remains temporarily so older clients fail
    explicitly instead of receiving a generic 404.
    """
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "Direct appointment payment updates are disabled. "
            "Payment status is updated only after provider verification."
        ),
    )

# TODO(payment-integrity): In the appointment-specific provider verification
# path, bind the verified reference to the stored appointment reference,
# appointment.patient_id, expected amount, currency, appointment type, and a
# payable appointment state before setting payment_status="paid".

@router.put("/{appt_id}/cancel", response_model=AppointmentResponse)
def cancel_my_appointment(appt_id: int, db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found.",
        )
    require_patient_owner(appt, current_user)
    if appt.status not in {"pending", "awaiting_payment", "confirmed"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This appointment can no longer be cancelled.",
        )

    appointment_type = resolve_appointment_type(appt)
    if (
        appt.status == "confirmed"
        and appointment_type in {APPOINTMENT_TYPE_GENERAL_QUEUE, None}
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This consultation has already been accepted by a doctor and "
                "can no longer be cancelled."
            ),
        )

    if (
        appt.status == "confirmed"
        and appointment_type
        in {APPOINTMENT_TYPE_SPECIALIST_SCHEDULED, APPOINTMENT_TYPE_VIP_REQUEST}
        and consultation_has_opened(appt)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This consultation has already opened and can no longer "
                "be cancelled."
            ),
        )

    appt.status = "cancelled"
    if appt.slot and appt.slot_id == appt.slot.id:
        appt.slot.is_booked = False
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
            Appointment.appointment_type == APPOINTMENT_TYPE_VIP_REQUEST,
            Appointment.slot_id == None,  # noqa: E711
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
            appointment_type=resolve_appointment_type(a),
            doctor_name=p_name,        # shown as "patient" on doctor's UI
            patient_name=p_name,
            status=a.status,
            payment_status=a.payment_status,
            is_acknowledged=getattr(a, 'is_acknowledged', False),
            start_time=a.slot.start_time if a.slot else a.start_time,
            patient_joined_at=getattr(a, 'patient_joined_at', None),
            doctor_joined_at=getattr(a, 'doctor_joined_at', None),
            consultation_started_at=getattr(a, 'consultation_started_at', None),
            no_show_marked_at=getattr(a, 'no_show_marked_at', None),
            refund_status=getattr(a, 'refund_status', None),
            refund_reference=getattr(a, 'refund_reference', None),
            refund_amount=getattr(a, 'refund_amount', None),
            refund_processed_at=getattr(a, 'refund_processed_at', None),
            notes=enriched_notes,
            has_review=False,
            amount=getattr(a, 'amount', 0.0),
        ))
    return results

@router.get("/doctor/queue", response_model=List[AppointmentResponse])
def get_general_queue(db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    doctor = require_approved_doctor(current_user, db)

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
        .filter(
            Appointment.appointment_type == APPOINTMENT_TYPE_GENERAL_QUEUE,
            Appointment.doctor_id == None,  # noqa: E711
            Appointment.slot_id == None,  # noqa: E711
            Appointment.status == "pending",
            Appointment.payment_status == "paid",
        )
        .all()
    )

    logger.info("[doctor/queue] Found %d item(s) in general queue.", len(appts))

    results = []
    for a in appts:
        # Before claim, expose only the patient's submitted triage text.
        # Identity, patient ID, historical consultations, prescriptions, and
        # other vault data remain hidden until the doctor is assigned.
        triage_summary = (a.notes or "").strip()
        if len(triage_summary) > 500:
            triage_summary = f"{triage_summary[:500].rstrip()}..."

        results.append(AppointmentResponse(
            id=a.id,
            doctor_id=a.doctor_id,
            patient_id=None,
            appointment_type=APPOINTMENT_TYPE_GENERAL_QUEUE,
            doctor_name="General Queue Patient",
            patient_name=None,
            status=a.status,
            payment_status=a.payment_status,
            is_acknowledged=getattr(a, 'is_acknowledged', False),
            start_time=a.start_time,
            patient_joined_at=getattr(a, 'patient_joined_at', None),
            doctor_joined_at=getattr(a, 'doctor_joined_at', None),
            consultation_started_at=getattr(a, 'consultation_started_at', None),
            no_show_marked_at=getattr(a, 'no_show_marked_at', None),
            refund_status=getattr(a, 'refund_status', None),
            refund_reference=getattr(a, 'refund_reference', None),
            refund_amount=getattr(a, 'refund_amount', None),
            refund_processed_at=getattr(a, 'refund_processed_at', None),
            notes=triage_summary or None,
            has_review=False,
            amount=getattr(a, 'amount', 0.0),
        ))
    return results

@router.put("/doctor/queue/{appt_id}/claim", response_model=AppointmentResponse)
def claim_appointment(appt_id: int, db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    doctor = require_approved_doctor(current_user, db)
    if not getattr(doctor, "is_available", False):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You must be available before claiming a general queue appointment.",
        )

    # One conditional UPDATE makes the claim atomic: after the first doctor
    # assigns the row, a concurrent claimant no longer matches doctor_id IS NULL.
    updated_rows = (
        db.query(Appointment)
        .filter(
            Appointment.id == appt_id,
            Appointment.appointment_type == APPOINTMENT_TYPE_GENERAL_QUEUE,
            Appointment.status == "pending",
            Appointment.payment_status == "paid",
            Appointment.doctor_id == None,  # noqa: E711
            Appointment.slot_id == None,  # noqa: E711
        )
        .update(
            {
                Appointment.doctor_id: doctor.id,
                Appointment.status: "confirmed",
                Appointment.start_time: datetime.utcnow(),
            },
            synchronize_session=False,
        )
    )

    if updated_rows != 1:
        db.rollback()
        existing = (
            db.query(Appointment)
            .filter(Appointment.id == appt_id)
            .first()
        )
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Appointment not found.",
            )

        # Produce the most specific workflow error available. If every
        # precondition still appears valid, another doctor won the race.
        require_general_queue_claimable(existing)
        if existing.appointment_type != APPOINTMENT_TYPE_GENERAL_QUEUE:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Legacy appointments without a durable general queue type cannot be claimed.",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This appointment was claimed by another doctor.",
        )

    db.commit()
    appt = (
        db.query(Appointment)
        .filter(Appointment.id == appt_id)
        .first()
    )
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
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found.",
        )
    doctor = require_assigned_doctor(appt, current_user, db)
    if appt.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only pending appointments can be accepted.",
        )
    if appt.payment_status != "paid":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An appointment cannot be accepted before payment is verified.",
        )

    appt.status = "confirmed"
    db.commit()
    db.refresh(appt)
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
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found.",
        )
    doctor = require_assigned_doctor(appt, current_user, db)
    if appt.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only pending appointments can be declined.",
        )

    appt.status = "cancelled"
    if appt.slot:
        appt.slot.is_booked = False
    db.commit()
    db.refresh(appt)
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
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found.",
        )
    doctor = require_assigned_doctor(appt, current_user, db)
    if appt.status not in {"awaiting_payment", "confirmed"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only proposed or confirmed appointments can be cancelled by a doctor.",
        )
    appointment_type = resolve_appointment_type(appt)
    if appt.status == "confirmed" and (
        appointment_type in {APPOINTMENT_TYPE_GENERAL_QUEUE, None}
        or consultation_has_opened(appt)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This consultation has already opened and can no longer "
                "be cancelled. Use the no-show or completion workflow."
            ),
        )

    appt.status = "cancelled"
    if appt.slot:
        appt.slot.is_booked = False
    db.commit()
    db.refresh(appt)
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
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found.",
        )
    doctor = require_assigned_doctor(appt, current_user, db)
    if appt.status != "confirmed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only confirmed appointments can be completed.",
        )
    if appt.payment_status != "paid":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An appointment cannot be completed before payment is verified.",
        )

    if getattr(appt, "consultation_started_at", None) is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The consultation cannot be completed before both participants join.",
        )

    complete_consultation(db, appt)
    db.commit()
    db.refresh(appt)
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
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found.")
    doctor = require_assigned_doctor(appt, current_user, db)

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
    # Fetch appointment and verify active-doctor assignment
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found.")
    doctor = require_assigned_doctor(appt, current_user, db)

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
            appointment_type=resolve_appointment_type(a),
            doctor_name=p_name,      # repurposed: carries patient name for doctor-side view
            patient_name=p_name,
            status=a.status,
            payment_status=a.payment_status,
            is_acknowledged=getattr(a, 'is_acknowledged', False),
            start_time=start,
            patient_joined_at=getattr(a, 'patient_joined_at', None),
            doctor_joined_at=getattr(a, 'doctor_joined_at', None),
            consultation_started_at=getattr(a, 'consultation_started_at', None),
            no_show_marked_at=getattr(a, 'no_show_marked_at', None),
            refund_status=getattr(a, 'refund_status', None),
            refund_reference=getattr(a, 'refund_reference', None),
            refund_amount=getattr(a, 'refund_amount', None),
            refund_processed_at=getattr(a, 'refund_processed_at', None),
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found.",
        )
    require_patient_owner(appt, current_user)
    if appt.status not in {"awaiting_payment", "confirmed"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only proposed or confirmed appointments can be acknowledged.",
        )

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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found.",
        )

    require_vip_requested_doctor(appt, current_user, db)
    if appt.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only pending VIP requests can receive a proposed time.",
        )
    if appt.payment_status != "unpaid":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A proposed time cannot be changed after payment is verified.",
        )

    # Guardrail: proposed time must not exceed 30 days from now.
    # Use UTC-aware comparison to avoid naive/aware datetime mixing.
    from datetime import timezone
    _max_date = datetime.now(timezone.utc) + timedelta(days=30)
    _proposed_utc = payload.proposed_time
    if _proposed_utc.tzinfo is None:
        # Treat naive datetimes (from older clients) as UTC
        _proposed_utc = _proposed_utc.replace(tzinfo=timezone.utc)
    if _proposed_utc <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Proposed time must be in the future.",
        )
    if _proposed_utc > _max_date:
        raise HTTPException(
            status_code=400,
            detail="Proposed time cannot exceed 30 days from today.",
        )

    # Update start time and status
    appt.start_time = as_naive_utc(_proposed_utc)
    appt.status = "awaiting_payment"
    db.commit()
    db.refresh(appt)

    p_name = f"{appt.patient.first_name} {appt.patient.last_name}" if appt.patient else "Unknown"
    
    return AppointmentResponse(
        id=appt.id,
        doctor_id=appt.doctor_id,
        patient_id=appt.patient_id,
        appointment_type=resolve_appointment_type(appt),
        doctor_name=p_name,
        patient_name=p_name,
        status=appt.status,
        payment_status=appt.payment_status,
        is_acknowledged=getattr(appt, 'is_acknowledged', False),
        start_time=appt.start_time,
        patient_joined_at=getattr(appt, 'patient_joined_at', None),
        doctor_joined_at=getattr(appt, 'doctor_joined_at', None),
        consultation_started_at=getattr(appt, 'consultation_started_at', None),
        no_show_marked_at=getattr(appt, 'no_show_marked_at', None),
        refund_status=getattr(appt, 'refund_status', None),
        refund_reference=getattr(appt, 'refund_reference', None),
        refund_amount=getattr(appt, 'refund_amount', None),
        refund_processed_at=getattr(appt, 'refund_processed_at', None),
        notes=appt.notes,
        has_review=False,
        amount=getattr(appt, 'amount', 0.0),
        paystack_reference=getattr(appt, 'paystack_reference', None)
    )


@router.post("/{appt_id}/complaint")
def raise_appointment_complaint(
    appt_id: int,
    payload: AppointmentComplaintRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """Allow a patient to raise a refund/dispute review within the 24h hold."""
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found.",
        )
    require_patient_owner(appt, current_user)

    if appt.status != "completed" or appt.payment_status != "paid":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only completed paid consultations can be reviewed for complaint refund.",
        )

    hold_until = consultation_payout_hold_until(appt)
    if hold_until is None or datetime.utcnow() > hold_until:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The 24-hour complaint window for this consultation has closed.",
        )

    reason = payload.reason.strip()
    if not reason:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Complaint reason is required.",
        )
    if len(reason) > 1000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Complaint reason is too long.",
        )

    if appt.refund_status and appt.refund_status != "rejected":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This consultation is already under refund or dispute review.",
        )

    appt.refund_status = REFUND_STATUS_AWAITING_ADMIN
    appt.refund_amount = appt.amount
    appt.refund_last_error = f"Patient complaint: {reason}"
    db.commit()
    return {
        "status": "submitted",
        "appointment_id": appt.id,
        "refund_status": appt.refund_status,
        "message": "Your complaint has been sent for admin review.",
    }


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

    # Fetch and verify active-doctor assignment.
    appt = (
        db.query(Appointment)
        .options(joinedload(Appointment.patient))
        .filter(Appointment.id == payload.appointment_id)
        .first()
    )
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found.")
    doctor = require_assigned_doctor(appt, current_user, db)

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
