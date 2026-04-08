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
    total_revenue: float
    active_appointments: int

@router.get("/stats", response_model=AdminStats)
def get_admin_stats(db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    total_users = db.query(User).filter(User.role == "patient").count()
    total_doctors = db.query(User).filter(User.role == "doctor").count()
    subscribed_users = db.query(User).filter(User.plan == "premium").count()
    pending_verifications = db.query(Doctor).filter(Doctor.is_verified == False).count()
    
    paid_appts = db.query(Appointment).filter(Appointment.payment_status == "paid").all()
    total_revenue = sum(a.amount for a in paid_appts)
    
    active_appointments = db.query(Appointment).filter(Appointment.status.in_(["pending", "confirmed"])).count()

    return {
        "total_users": total_users,
        "total_doctors": total_doctors,
        "subscribed_users": subscribed_users,
        "pending_verifications": pending_verifications,
        "total_revenue": total_revenue,
        "active_appointments": active_appointments
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

# --- NEW: FETCH PENDING DOCTORS ---
@router.get("/doctors/pending", response_model=List[DoctorResponse])
def get_pending_doctors(db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    # Fetch ONLY unverified doctors
    return db.query(Doctor).filter(Doctor.is_verified == False).all()

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
        f"Congratulations Dr. {doctor.full_name}!\n\nYour MDQ+ doctor account is now active. You can log in and start accepting patients."
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
    Sets status to 'rejected', stores the reason, and emails the doctor.
    """
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    user = db.query(User).filter(User.id == doctor.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Associated user account not found")

    # --- 1. Update Doctor Record ---
    doctor.is_verified = False
    doctor.is_available = False
    doctor.status = "rejected"
    doctor.rejection_reason = payload.rejection_reason

    # --- 2. Audit Log ---
    audit = AuditLog(
        admin_id=admin.id,
        resource=f"Doctor:{doctor.id} ({doctor.full_name})",
        reason=f"Rejected: {payload.rejection_reason}",
    )
    db.add(audit)
    db.commit()

    # --- 3. Send Rejection Email via Resend ---
    rejection_email_html = f"""
    <div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 24px; color: #1a1a2e;">
        <div style="text-align: center; padding-bottom: 16px; border-bottom: 2px solid #e94560;">
            <h1 style="margin: 0; color: #1a1a2e; font-size: 22px;">MDQ<span style="color: #e94560;">+</span></h1>
            <p style="margin: 4px 0 0; color: #6c757d; font-size: 13px;">Medical Professional Verification</p>
        </div>

        <div style="padding: 24px 0;">
            <p>Dear <strong>Dr. {doctor.full_name}</strong>,</p>

            <p>Thank you for your interest in joining the MDQ+ network. After careful review of your submitted
            credentials, we regret to inform you that your application <strong>could not be approved</strong>
            at this time.</p>

            <div style="background-color: #fff3f3; border-left: 4px solid #e94560; padding: 16px; margin: 20px 0; border-radius: 4px;">
                <p style="margin: 0 0 4px; font-weight: 600; color: #e94560;">Reason for Non-Approval:</p>
                <p style="margin: 0; color: #333;">{payload.rejection_reason}</p>
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
            <p>&copy; {datetime.now().year} MDQ+ Health Technologies. All rights reserved.</p>
            <p>This is an automated message. Please do not reply directly to this email.</p>
        </div>
    </div>
    """

    background_tasks.add_task(
        send_email,
        user.email,
        "MDQ+: Update on Your Verification Application",
        rejection_email_html,
    )

    return {
        "message": f"Doctor {doctor.full_name}'s application has been rejected.",
        "doctor_id": doctor.id,
        "status": "rejected",
        "rejection_reason": payload.rejection_reason,
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