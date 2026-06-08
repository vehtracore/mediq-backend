from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from app.api.v1.auth import send_email  # Import email helper
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
    subscribed_users: int
    pending_verifications: int
    total_completed_consultations: int
    active_appointments: int

@router.get("/stats", response_model=AdminStats)
def get_admin_stats(db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    total_users = db.query(User).filter(User.role == "patient").count()
    total_doctors = db.query(User).filter(User.role == "doctor").count()

    # --- True Active Subscribers ---
    # Count 1: Primary account holders on an active premium or family plan.
    primary_subscribers = (
        db.query(User)
        .filter(
            User.role == "patient",
            User.plan.in_(["premium", "family"]),
            User.primary_account_id == None,  # noqa: E711  — must be a primary holder
        )
        .count()
    )

    # Count 2: Dependent users whose primary account holder is on an active
    # family plan. We join User (dependent) → User (primary) and filter on
    # the primary's plan to avoid counting orphaned / expired links.
    PrimaryUser = db.query(User).subquery()  # alias for the self-join
    dependents_covered = (
        db.query(User)
        .join(
            PrimaryUser,
            User.primary_account_id == PrimaryUser.c.id,
        )
        .filter(
            PrimaryUser.c.plan.in_(["premium", "family"]),
        )
        .count()
    )

    subscribed_users = primary_subscribers + dependents_covered

    pending_verifications = db.query(Doctor).filter(Doctor.is_verified == False).count()

    # --- Total Completed Consultations ---
    # Count of all appointments that have reached a terminal "completed" state.
    total_completed_consultations = (
        db.query(Appointment)
        .filter(Appointment.status == "completed")
        .count()
    )

    active_appointments = (
        db.query(Appointment)
        .filter(Appointment.status.in_(["pending", "confirmed"]))
        .count()
    )

    return {
        "total_users": total_users,
        "total_doctors": total_doctors,
        "subscribed_users": subscribed_users,
        "pending_verifications": pending_verifications,
        "total_completed_consultations": total_completed_consultations,
        "active_appointments": active_appointments,
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
    status = "suspended" if user.is_banned else "reactivated"
    return {"message": f"User is now {status}."}

# --- FETCH PENDING DOCTORS ---
@router.get("/doctors/pending", response_model=List[DoctorResponse])
def get_pending_doctors(db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    # ✅ FIX: Filter on status == 'pending', NOT just is_verified == False.
    # A rejected doctor also has is_verified=False, so the old filter was
    # returning them — making the rejection look like it never happened.
    return db.query(Doctor).filter(Doctor.status == "pending").all()

@router.put("/doctors/{doctor_id}/verify")
def verify_doctor(doctor_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor: raise HTTPException(404, "Doctor not found")
    
    user = db.query(User).filter(User.id == doctor.user_id).first()
    if not user: raise HTTPException(404, "User for doctor not found")

    # ✅ FIX: Set ALL required fields for login to work
    doctor.is_verified = True
    doctor.is_available = True
    doctor.status = "active"  # <-- THIS WAS MISSING!
    user.is_active = True
    
    db.commit()
    
    # ✅ FIX: Send email notification to the doctor
    background_tasks.add_task(
        send_email,
        user.email,
        "MDQ+: Your Application is Approved!",
        f"Congratulations {doctor.full_name}!\n\nYour MDQ+ doctor account is now active. You can log in and start accepting patients."
    )
    
    return {"message": "Doctor verified and account activated."}


# --- Pydantic Schema for Rejection ---
class RejectDoctorRequest(BaseModel):
    rejection_reason: str

@router.post("/doctors/{doctor_id}/reject")
def reject_doctor(
    doctor_id: int,
    payload: RejectDoctorRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """
    Reject a doctor's MDCN verification application.
    Guarantees DB is committed before returning 200 OK.
    Email construction is isolated so it can never roll back the transaction.
    """
    import logging
    _log = logging.getLogger("uvicorn.error")

    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    user = db.query(User).filter(User.id == doctor.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Associated user account not found")

    # ── SNAPSHOT values BEFORE commit ────────────────────────────────────────
    # SQLAlchemy expires all ORM attributes after db.commit() (expire_on_commit
    # is True by default). Accessing doctor.full_name AFTER commit triggers a
    # lazy-load SELECT which can fail in background-task threading contexts.
    # Capture everything we need as plain Python strings right now.
    doctor_id_snap      = doctor.id
    doctor_name_snap    = doctor.full_name
    user_email_snap     = user.email
    rejection_reason    = payload.rejection_reason
    current_year        = datetime.now().year

    # ── 1. Mutate the Doctor record ──────────────────────────────────────────
    doctor.is_verified      = False
    doctor.is_available     = False
    doctor.status           = "rejected"
    doctor.rejection_reason = rejection_reason

    # ── 1b. Unlock the User account so they can log in ───────────────────────
    # is_active=False was set at registration to block login until admin review.
    # A rejection IS a completed review — the doctor must be able to log in
    # to reach the /doctor_rejected quarantine screen and reapply.
    # doctor.status == 'rejected' is what the login gate uses to route them
    # to quarantine instead of the main dashboard. is_active is NOT that gate.
    user.is_active = True

    # ── 2. Audit Log ─────────────────────────────────────────────────────────
    audit = AuditLog(
        admin_id=admin.id,
        resource=f"Doctor:{doctor_id_snap} ({doctor_name_snap})",
        reason=f"Rejected: {rejection_reason}",
    )
    db.add(audit)

    # ── 3. Commit — this is the single source of truth ───────────────────────
    # If this raises, SQLAlchemy rolls back and FastAPI returns a 500.
    # No 200 OK is ever sent unless this line succeeds.
    try:
        db.commit()
        db.refresh(doctor)  # Confirm the persisted state back from the DB
        _log.info(
            f"[REJECT] ✅ DB committed | doctor_id={doctor_id_snap} "
            f"status={doctor.status} | reason='{rejection_reason}'"
        )
    except Exception as db_err:
        db.rollback()
        _log.error(f"[REJECT] ❌ DB commit FAILED for doctor_id={doctor_id_snap}: {db_err!r}")
        raise HTTPException(status_code=500, detail="Database error: could not persist rejection.")

    # ── 4. Schedule email — AFTER commit, in its own try/except ──────────────
    # Building the HTML template or scheduling the task must NEVER be able to
    # crash and give the impression the DB write failed. The commit is already
    # done; this block is best-effort.
    try:
        rejection_email_html = f"""
    <div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 24px; color: #1a1a2e;">
        <div style="text-align: center; padding-bottom: 16px; border-bottom: 2px solid #e94560;">
            <h1 style="margin: 0; color: #1a1a2e; font-size: 22px;">MDQ<span style="color: #e94560;">+</span></h1>
            <p style="margin: 4px 0 0; color: #6c757d; font-size: 13px;">Medical Professional Verification</p>
        </div>
        <div style="padding: 24px 0;">
            <p>Dear <strong>{doctor_name_snap}</strong>,</p>
            <p>Thank you for your interest in joining the MDQ+ network. After careful review of your submitted
            credentials, we regret to inform you that your application <strong>could not be approved</strong>
            at this time.</p>
            <div style="background-color: #fff3f3; border-left: 4px solid #e94560; padding: 16px; margin: 20px 0; border-radius: 4px;">
                <p style="margin: 0 0 4px; font-weight: 600; color: #e94560;">Reason for Non-Approval:</p>
                <p style="margin: 0; color: #333;">{rejection_reason}</p>
            </div>
            <h3 style="color: #1a1a2e; margin-bottom: 8px;">Next Steps</h3>
            <ol style="color: #333; line-height: 1.8;">
                <li>Review the reason stated above carefully.</li>
                <li>Log back into the <strong>MDQ+</strong> application.</li>
                <li>Navigate to your <strong>Profile &rarr; Verification Documents</strong> section.</li>
                <li>Upload the corrected or updated document(s) and re-submit your application.</li>
            </ol>
            <p style="color: #6c757d; font-size: 13px; margin-top: 24px;">
                If you believe this decision was made in error, please contact our support team at
                <a href="mailto:support@mdqplus.com" style="color: #0062cc;">support@mdqplus.com</a>.
            </p>
        </div>
        <div style="border-top: 1px solid #dee2e6; padding-top: 16px; text-align: center; color: #6c757d; font-size: 12px;">
            <p>&copy; {current_year} MDQ+ Health Technologies. All rights reserved.</p>
            <p>This is an automated message. Please do not reply directly to this email.</p>
        </div>
    </div>
        """
        background_tasks.add_task(
            send_email,
            user_email_snap,
            "MDQ+: Update on Your Verification Application",
            rejection_email_html,
        )
        _log.info(f"[REJECT] 📧 Email task queued for {user_email_snap}")
    except Exception as email_err:
        # Log it, but DO NOT re-raise. The DB is already committed.
        _log.error(
            f"[REJECT] ⚠️ Email task could not be queued for {user_email_snap}: {email_err!r}. "
            "DB commit is still valid — rejection was persisted."
        )

    return {
        "message": f"Doctor {doctor_name_snap}'s application has been rejected.",
        "doctor_id": doctor_id_snap,
        "status": "rejected",
        "rejection_reason": rejection_reason,
    }

# --- 🛠️ TEMP: DATABASE MIGRATION HELPER ---
from sqlalchemy import text
@router.post("/fix-schema")
def fix_schema(db: Session = Depends(get_db)):
    """Run this ONCE to add the missing column"""
    try:
        # PostgreSQL specific commands
        db.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS image_url VARCHAR;"))
        db.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS verification_token VARCHAR;"))
        db.execute(text("ALTER TABLE doctors ADD COLUMN IF NOT EXISTS rejection_reason VARCHAR;"))
        # Backfill: existing users (created before verification) should be verified
        db.execute(text("UPDATE users SET is_verified = TRUE WHERE is_verified IS NULL OR is_verified = FALSE;"))
        db.commit()
        return {"message": "✅ Schema updated + existing users marked as verified."}
    except Exception as e:
        return {"message": f"❌ Error updating schema: {e}"}

# --- 🛠️ TEMP: Delete test users ---
@router.post("/delete-test-users")
def delete_test_users(emails: dict, db: Session = Depends(get_db)):
    """Delete test users by email list. Body: {"emails": ["a@b.com"]}"""
    try:
        deleted = []
        for email in emails.get("emails", []):
            user = db.query(User).filter(User.email == email).first()
            if user:
                # Delete associated doctor record first (FK constraint)
                doctor = db.query(Doctor).filter(Doctor.user_id == user.id).first()
                if doctor:
                    db.delete(doctor)
                db.delete(user)
                deleted.append(email)
        db.commit()
        return {"message": f"Deleted {len(deleted)} users", "deleted": deleted}
    except Exception as e:
        db.rollback()
        return {"message": f"Error: {e}"}