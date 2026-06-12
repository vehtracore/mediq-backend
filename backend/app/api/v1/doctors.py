
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.models.doctor import Doctor
from app.models.user import User
from app.models.appointment import Appointment
from app.schemas.doctor import DoctorResponse, DoctorUpdate, ReapplyRequest, PayoutSettingsRequest
from app.api import deps
from app.services.paystack_service import paystack_service

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
    if data.hourly_rate is not None and data.hourly_rate < 3000:
        raise HTTPException(status_code=400, detail="Minimum consultation fee must be at least ₦3,000.")
    if data.hourly_rate: doctor.hourly_rate = data.hourly_rate
    if data.years_experience: doctor.years_experience = data.years_experience
    if data.image_url: doctor.image_url = data.image_url

    db.commit()
    db.refresh(doctor)
    return doctor


@router.put("/me/payout-settings", response_model=DoctorResponse)
async def update_payout_settings(
    payload: PayoutSettingsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """
    PUT /api/v1/doctors/me/payout-settings

    Links a verified Nigerian bank account to the authenticated doctor's profile
    by creating a Paystack split-payment subaccount. The platform retains 30 %
    of every transaction; the remainder is routed directly to the doctor's bank.

    On success the subaccount_code, bank_code, and account_number are persisted
    against the Doctor record and returned in the response.

    Raises:
        403  — caller is not a doctor
        404  — doctor profile row not found
        400  — Paystack rejected the bank details (message forwarded verbatim)
        503  — Paystack could not be reached (network error)
    """
    if current_user.role != "doctor":
        raise HTTPException(status_code=403, detail="Only doctors can configure payout settings.")

    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor profile not found.")

    logger.info(
        "[PAYOUT] Creating subaccount for doctor_id=%s | bank=%s | account=%s",
        doctor.id,
        payload.bank_code,
        payload.account_number,
    )

    # ── Step 1: Resolve account name and verify it matches the doctor ─────────
    resolved_name: str = await paystack_service.resolve_account(
        bank_code=payload.bank_code,
        account_number=payload.account_number,
    )

    # Forgiving name comparison: split both names into lowercase tokens and
    # require at least ONE token to match. This tolerates:
    #   • Name-ordering differences ("OKAFOR JAMES" vs "James Okafor")
    #   • Middle-name omissions ("AMAKA C. OBI" vs "Amaka Obi")
    #   • All-caps vs title-case differences from the bank
    doctor_tokens = set(doctor.full_name.lower().split())
    bank_tokens   = set(resolved_name.lower().split())
    has_match     = bool(doctor_tokens & bank_tokens)  # set intersection

    if not has_match:
        logger.warning(
            "[PAYOUT] ❌ Name mismatch — doctor='%s' | bank_account='%s'",
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
        "[PAYOUT] ✅ Name verified — doctor='%s' | bank_account='%s'",
        doctor.full_name,
        resolved_name,
    )

    # ── Step 2: Create the Paystack subaccount ────────────────────────────────
    # This call raises HTTPException(400) or (503) on failure — let it propagate.
    subaccount_code: str = await paystack_service.create_doctor_subaccount(

        business_name=doctor.full_name,
        bank_code=payload.bank_code,
        account_number=payload.account_number,
        percentage_charge=30.0,
    )

    doctor.bank_code = payload.bank_code
    doctor.account_number = payload.account_number
    doctor.paystack_subaccount_code = subaccount_code

    try:
        db.commit()
        db.refresh(doctor)
    except Exception as exc:
        db.rollback()
        logger.error("[PAYOUT] DB commit failed after subaccount creation: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Subaccount was created on Paystack but could not be saved. Contact support.",
        ) from exc

    logger.info(
        "[PAYOUT] ✅ Subaccount saved — doctor_id=%s | code=%s",
        doctor.id,
        subaccount_code,
    )
    return doctor

@router.get("/{doctor_id}", response_model=DoctorResponse)
def read_doctor(doctor_id: int, db: Session = Depends(get_db)):
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor: raise HTTPException(404, "Doctor not found")
    return doctor
