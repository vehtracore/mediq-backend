
import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.core.limiter import limiter
from app.models.doctor import Doctor
from app.models.user import User
from app.models.appointment import Appointment
from app.models.consultation_payout import ConsultationPayout
from app.schemas.doctor import DoctorResponse, DoctorUpdate, ReapplyRequest, PayoutSettingsRequest
from app.api import deps
from app.services.consultation_pricing import (
    DEFAULT_CONSULTATION_DURATION_MINUTES,
    minimum_consultation_fee,
)
from app.services.paystack_service import paystack_service
from app.services.consultation_payout_service import (
    PAYOUT_AMOUNT_SYNC_STATUSES,
    expected_consultation_payout_amount,
)

logger = logging.getLogger("uvicorn.error")

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
                logger.warning("[DOCTORS] Validation error for Doctor ID=%s, Name=%s: %s", doc.id, doc.full_name, ve, exc_info=True)
                # Still include it with lenient fields
                results.append(DoctorResponse.model_validate(doc, strict=False))
        return results
    except Exception as e:
        logger.error("[DOCTORS] Failed to list doctors: %s", e, exc_info=True)
        raise

@router.get("/stats")
def get_doctor_stats(db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    if current_user.role != "doctor": raise HTTPException(403, "Not a doctor")
    
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    if not doctor: raise HTTPException(404, "Profile not found")
    
    # 1. Total Paid â€” webhook-confirmed funds (transfer.success credited)
    total_paid = float(doctor.total_earnings or 0)

    # 2. Pending Settlement — earned but not yet sent via Paystack.
    # Normalize stale unprocessed ledger rows to the current 63% doctor share
    # before returning the money-card value.
    pending_payouts = (
        db.query(ConsultationPayout)
        .filter(
            ConsultationPayout.doctor_id == doctor.id,
            ConsultationPayout.status.in_(
                ("awaiting_admin", "approved", "processing")
            ),
        )
        .all()
    )
    pending_total = Decimal("0.00")
    payout_amount_changed = False
    for payout in pending_payouts:
        amount = Decimal(str(payout.amount or 0)).quantize(Decimal("0.01"))
        if payout.status in PAYOUT_AMOUNT_SYNC_STATUSES:
            appointment = (
                db.query(Appointment)
                .filter(Appointment.id == payout.appointment_id)
                .first()
            )
            if appointment is not None:
                expected_amount = expected_consultation_payout_amount(appointment)
                if expected_amount > 0 and expected_amount != amount:
                    payout.amount = expected_amount
                    payout.last_error = None
                    amount = expected_amount
                    payout_amount_changed = True
        pending_total += amount
    if payout_amount_changed:
        db.commit()
    pending_settlement = float(pending_total)

    # 3. Calculate Unique Patients
    patient_ids = set()
    all_appts = db.query(Appointment).filter(Appointment.doctor_id == doctor.id).all()
    for a in all_appts:
        patient_ids.add(a.patient_id)
    
    return {
        "total_paid": total_paid,
        "pending_settlement": pending_settlement,
        "total_patients": len(patient_ids),
        "rating": doctor.rating,
        "reviews": doctor.review_count,
        "years_experience": doctor.years_experience
    }

@router.put("/me", response_model=DoctorResponse)
def update_doctor_me(data: DoctorUpdate, db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    if current_user.role != "doctor":
        raise HTTPException(
            status_code=403,
            detail="Only doctors can update doctor profiles.",
        )

    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    if not doctor: raise HTTPException(404, "Not found")

    duration = DEFAULT_CONSULTATION_DURATION_MINUTES
    fee = (
        data.consultation_fee
        if data.consultation_fee is not None
        else (doctor.consultation_fee or doctor.hourly_rate or 0.0)
    )
    minimum_fee = minimum_consultation_fee(duration)
    if fee < minimum_fee:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Minimum consultation fee for {duration} minutes "
                f"is â‚¦{minimum_fee:,.0f}."
            ),
        )

    if data.bio is not None:
        doctor.bio = data.bio
    doctor.consultation_duration_minutes = duration
    if data.consultation_fee is not None:
        doctor.consultation_fee = fee
        doctor.hourly_rate = fee
    if data.years_experience is not None:
        doctor.years_experience = data.years_experience
    if data.image_url is not None:
        doctor.image_url = data.image_url

    db.commit()
    db.refresh(doctor)
    return doctor


@router.put("/me/payout-settings", response_model=DoctorResponse)
@limiter.limit("5/hour")
@limiter.limit("2/minute")
async def update_payout_settings(
    request: Request,
    payload: PayoutSettingsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """
    PUT /api/v1/doctors/me/payout-settings

    Links a verified Nigerian bank account to the authenticated doctor's profile.

    Consultation payments are collected by MDQ+ first. Doctor transfers are
    created later after the 24-hour complaint hold and admin approval, so this
    endpoint only verifies and stores bank details.

    Raises:
        403  â€” caller is not a doctor
        404  â€” doctor profile row not found
        400  â€” Paystack rejected the bank details (message forwarded verbatim)
        503  â€” Paystack could not be reached (network error)
    """
    if current_user.role != "doctor":
        raise HTTPException(status_code=403, detail="Only doctors can configure payout settings.")

    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found.")

    if not doctor.is_verified or doctor.status != "active":
        raise HTTPException(
            status_code=403,
            detail="Payout settings can only be configured by verified doctors.",
        )

    masked_account = f"******{payload.account_number[-4:]}"
    logger.info(
        "[PAYOUT] Saving payout bank for doctor_id=%s | bank=%s | account=%s",
        doctor.id,
        payload.bank_code,
        masked_account,
    )

    # â”€â”€ Step 1: Resolve account name and verify it matches the doctor â”€â”€â”€â”€â”€â”€â”€â”€â”€
    resolved_name: str = await paystack_service.resolve_account(
        bank_code=payload.bank_code,
        account_number=payload.account_number,
    )

    # Forgiving name comparison: split both names into lowercase tokens and
    # require at least ONE token to match. This tolerates:
    #   â€¢ Name-ordering differences ("OKAFOR JAMES" vs "James Okafor")
    #   â€¢ Middle-name omissions ("AMAKA C. OBI" vs "Amaka Obi")
    #   â€¢ All-caps vs title-case differences from the bank
    doctor_tokens = set(doctor.full_name.lower().split())
    bank_tokens   = set(resolved_name.lower().split())
    has_match     = bool(doctor_tokens & bank_tokens)  # set intersection

    if not has_match:
        logger.warning(
            "[PAYOUT] âŒ Name mismatch â€” doctor='%s' | bank_account='%s'",
            doctor.full_name,
            resolved_name,
        )
        raise HTTPException(
            status_code=400,
            detail=(
                f"Bank account name '{resolved_name}' does not match your "
                "registered profile name. Please use an account in your name."
            ),
        )

    logger.info(
        "[PAYOUT] âœ… Name verified â€” doctor='%s' | bank_account='%s'",
        doctor.full_name,
        resolved_name,
    )

    # Step 2: Store verified bank details. The transfer recipient is created
    # lazily by the admin-approved payout worker when a transfer is due.
    doctor.bank_code = payload.bank_code
    doctor.account_number = payload.account_number
    doctor.paystack_subaccount_code = None
    doctor.paystack_recipient_code = None
    db.query(ConsultationPayout).filter(
        ConsultationPayout.doctor_id == doctor.id,
        ConsultationPayout.status == "blocked",
        ConsultationPayout.approved_at.is_not(None),
    ).update(
        {
            ConsultationPayout.status: "approved",
            ConsultationPayout.last_error: None,
        },
        synchronize_session=False,
    )

    try:
        db.commit()
        db.refresh(doctor)
    except Exception as exc:
        db.rollback()
        logger.error("[PAYOUT] DB commit failed after subaccount creation: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Payout settings could not be saved. Please try again.",
        ) from exc

    logger.info(
        "[PAYOUT] Payout bank saved for doctor_id=%s",
        doctor.id,
    )
    return doctor

@router.get("/{doctor_id}", response_model=DoctorResponse)
def read_doctor(doctor_id: int, db: Session = Depends(get_db)):
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor: raise HTTPException(404, "Doctor not found")
    return doctor
