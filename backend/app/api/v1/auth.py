from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Request, Form, File, UploadFile
from fastapi.responses import HTMLResponse
import uuid
from pydantic import EmailStr
from sqlalchemy.orm import Session
from datetime import date, datetime, timezone
from app.core.database import get_db
from app.models.user import User
from app.models.doctor import Doctor
from app.schemas.user import UserCreate, UserResponse, LoginRequest, Token, UserUpdate, RefreshRequest, DeviceTokenUpdate
from app.schemas.doctor import DoctorResponse
from app.core import security
from app.api import deps
from app.core.limiter import limiter
from app.services.media_service import upload_image

router = APIRouter()

# --- 🧪 DIAGNOSTIC: Test Email Endpoint ---
@router.get("/test-email/{email}")
def test_email_endpoint(email: str):
    """
    Diagnostic endpoint to test email delivery.
    Sends synchronously and returns result directly.
    """
    import os
    import resend
    
    # Debug: List all env vars that contain 'RESEND' or start with key letters
    all_env = os.environ
    resend_vars = {k: v[:10]+"..." if v else v for k, v in all_env.items() if "RESEND" in k.upper()}
    
    api_key = os.getenv("RESEND_API_KEY")
    from_email = os.getenv("RESEND_FROM_EMAIL", "mdqplus <noreply@mdqplus.com>")
    
    debug_info = {
        "resend_env_vars_found": resend_vars,
        "api_key_present": bool(api_key),
        "api_key_prefix": api_key[:10] + "..." if api_key else None
    }
    
    if not api_key:
        return {"success": False, "error": "RESEND_API_KEY not found", "debug": debug_info}
    
    try:
        resend.api_key = api_key
        
        result = resend.Emails.send({
            "from": from_email,
            "to": [email],
            "subject": "mdqplus Email Test",
            "text": "This is a test email from mdqplus. If you received this, email delivery is working!"
        })
        
        return {"success": True, "email_id": result.get("id"), "sent_to": email, "debug": debug_info}
        
    except Exception as e:
        return {"success": False, "error": str(e), "debug": debug_info}

# --- 📧 EMAIL SERVICE (Resend HTTP API) ---
import os
import logging
import resend

# Configure logger for email service
logger = logging.getLogger("uvicorn.error")

def send_email(to_email: str, subject: str, body: str):
    """
    Send email using Resend HTTP API.
    Logs are intentionally verbose so failures are visible in Render's log stream.
    """
    logger.info(f"[EMAIL] >>> START send_email | to={to_email} | subject='{subject}'")

    api_key = os.getenv("RESEND_API_KEY")
    from_email = os.getenv("RESEND_FROM_EMAIL", "MDQ+ <noreply@mdqplus.com>")

    # ── Guard: API key must exist ─────────────────────────────────────────────
    if not api_key:
        logger.error(
            "[EMAIL] FATAL: RESEND_API_KEY environment variable is NOT SET. "
            "Go to Render → your service → Environment and add it."
        )
        return

    logger.info(
        f"[EMAIL] Config OK | key_prefix={api_key[:8]}... | from={from_email}"
    )

    try:
        resend.api_key = api_key

        payload = {
            "from": from_email,
            "to": [to_email],
            "subject": subject,
            "html": body if body.strip().startswith("<") else body.replace("\n", "<br>"),
        }
        logger.info(f"[EMAIL] Sending payload to Resend API: to={to_email}")

        result = resend.Emails.send(payload)

        # The SDK returns a dict-like object — extract the ID safely
        email_id = result.get("id") if isinstance(result, dict) else getattr(result, "id", "N/A")
        logger.info(f"[EMAIL] SUCCESS | id={email_id} | to={to_email}")

    except Exception as e:
        # ── Aggressive diagnostic logging ─────────────────────────────────────
        # str(e) alone is often useless for Resend SDK errors.
        # We extract every available attribute to surface the real cause.
        error_type = type(e).__name__
        error_str  = str(e)

        # Resend SDK wraps API errors — try to pull structured fields
        resend_name    = getattr(e, "name",       None)   # e.g. "validation_error"
        resend_message = getattr(e, "message",    None)   # human-readable reason
        resend_status  = getattr(e, "status_code", None)  # HTTP status from Resend
        raw_repr       = repr(e)                           # full Python repr as fallback

        logger.error(
            "[EMAIL] ❌ FAILED TO SEND EMAIL\n"
            f"  │ to            : {to_email}\n"
            f"  │ subject       : {subject}\n"
            f"  │ from          : {from_email}\n"
            f"  │ error_type    : {error_type}\n"
            f"  │ error_str     : {error_str}\n"
            f"  │ resend.name   : {resend_name}\n"
            f"  │ resend.message: {resend_message}\n"
            f"  │ resend.status : {resend_status}\n"
            f"  │ raw_repr      : {raw_repr}\n"
            "  └─ Check Render logs for the line above to diagnose the Resend failure."
        )

@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(user: UserCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.email == user.email).first()
    if db_user: raise HTTPException(400, detail="Email already registered")
    
    hashed_pwd = security.get_password_hash(user.password)
    new_user = User(
        email=user.email, 
        first_name=user.first_name, 
        last_name=user.last_name, 
        dob=user.dob, 
        location=user.location, 
        hashed_password=hashed_pwd, 
        role=user.role,
        is_verified=False, # ✅ Set to False so they MUST verify
        verification_token=str(uuid.uuid4()) # ✅ Generate Token
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    # ✅ Background Task: Send Verification Email
    backend_url = os.getenv("BACKEND_URL", "http://localhost:8000")
    verification_link = f"{backend_url}/api/v1/auth/verify-email?token={new_user.verification_token}"
    
    background_tasks.add_task(
        send_email, 
        new_user.email, 
        "Verify your mdqplus Account", 
        f"Welcome to mdqplus! PLease click the link below to verify your account:<br><br><a href='{verification_link}'>Verify Email</a>"
    )

    return new_user

@router.post("/doctor/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_doctor(
    background_tasks: BackgroundTasks,
    email: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(...),
    specialty: str = Form(...),
    license_number: str = Form(...),
    mdcn_license: UploadFile = File(...),
    indemnity_certificate: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(400, detail="Email registered")
    if db.query(Doctor).filter(Doctor.license_number == license_number).first():
        raise HTTPException(400, detail="License registered")

    # Upload both documents to Cloudinary
    mdcn_license_url = await upload_image(mdcn_license, folder="mdq_plus/doctor_licenses")
    indemnity_cert_url = await upload_image(indemnity_certificate, folder="mdq_plus/indemnity_certs")

    hashed_pwd = security.get_password_hash(password)
    names = full_name.split(" ")
    
    # ✅ Doctor user is INACTIVE initially
    new_user = User(
        email=email, 
        first_name=names[0], 
        last_name=names[-1] if len(names)>1 else "", 
        hashed_password=hashed_pwd, 
        role="doctor", 
        is_active=False, # Wait for Admin
        dob=date(1980, 1, 1), 
        location="Princeton-Plainsboro",
        is_verified=False,
        verification_token=str(uuid.uuid4()) # ✅ Generate Token
    )
    db.add(new_user)
    db.flush()

    new_doctor = Doctor(
        user_id=new_user.id, 
        full_name=full_name, 
        specialty=specialty, 
        license_number=license_number,
        mdcn_license_url=mdcn_license_url,
        indemnity_cert_url=indemnity_cert_url,
        is_verified=False, 
        is_available=False, 
        hourly_rate=0.0,
        status="pending" # ✅ Pending State
    )
    db.add(new_doctor)
    db.commit()
    db.refresh(new_user)

    # ✅ Generate the Verification Link
    backend_url = os.getenv("BACKEND_URL", "https://your-render-url.onrender.com") # Update if needed
    verification_link = f"{backend_url}/api/v1/auth/verify-email?token={new_user.verification_token}"

    # ✅ Email 1: Confirmation + Verification Link
    background_tasks.add_task(
        send_email,
        email,
        "mdqplus: Application Received & Verify Email",
        f"Hello Dr. {full_name},<br><br>"
        f"Thank you for applying to join mdqplus!<br><br>"
        f"<b>ACTION REQUIRED:</b> Please verify your email address by clicking the link below:<br>"
        f"<a href='{verification_link}'>Verify My Email</a><br><br>"
        f"Your application is currently pending admin review based on your submitted documents. "
        f"You will receive another email once your account is approved.<br><br>"
        f"- The mdqplus Team"
    )

    # ✅ Email 2: Notify Admin (using SMTP_EMAIL as admin for now)
    admin_email = os.getenv("SMTP_EMAIL", "admin@mediq.com")
    background_tasks.add_task(
        send_email,
        admin_email,
        "mdqplus: New Doctor Application",
        f"Dr. {full_name} has applied.\n\nEmail: {email}\nLicense: {license_number}\n\nPlease review in the Admin Dashboard."
    )

    return new_user

@router.post("/login", response_model=Token)
@limiter.limit("5/minute")
def login(request: Request, login_data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == login_data.email).first()
    if not user or not security.verify_password(login_data.password, user.hashed_password):
        raise HTTPException(401, detail="Incorrect email or password", headers={"WWW-Authenticate": "Bearer"})

    # ── is_active gate ────────────────────────────────────────────────────────
    # is_active=False means "pending admin first-review" for doctors.
    # However, rejected doctors must be allowed to log in (they go to the
    # quarantine screen). We do a quick status lookup FIRST so we can make an
    # informed decision before raising the inactive exception.
    doctor_status: str | None = None
    if user.role == "doctor":
        doctor = db.query(Doctor).filter(Doctor.user_id == user.id).first()
        if not doctor:
            raise HTTPException(400, detail="Doctor profile not found")
        doctor_status = doctor.status

    # Block if inactive, UNLESS this is a rejected doctor (they have a right
    # to log in so they can reach /doctor_rejected and reapply).
    if not user.is_active and doctor_status != "rejected":
        raise HTTPException(400, detail="Account is pending approval or inactive")

    # ── Email verification gate ───────────────────────────────────────────────
    if not user.is_verified:
        raise HTTPException(403, detail="Please verify your email before logging in. Check your inbox for a verification link.")

    # ── Doctor status gate ────────────────────────────────────────────────────
    # 'active'   → proceeds to /doctor_home
    # 'rejected' → proceeds to /doctor_rejected  (quarantine, can reapply)
    # 'pending'  → blocked here (admin hasn't reviewed yet)
    if doctor_status == "pending":
        raise HTTPException(400, detail="Doctor account is pending approval")

    access_token = security.create_access_token(data={"sub": user.email})
    refresh_token = security.create_refresh_token(data={"sub": user.email})
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "doctor_status": doctor_status,  # Flutter uses this to pick the right screen
    }

@router.get("/me", response_model=UserResponse)
def read_users_me(current_user: User = Depends(deps.get_current_user)): return current_user

@router.post("/refresh", response_model=Token)
def refresh_token(body: RefreshRequest, db: Session = Depends(get_db)):
    """Exchange a valid refresh token for a new access + refresh token pair."""
    from jose import jwt, JWTError

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid refresh token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            body.refresh_token,
            security.SECRET_KEY,
            algorithms=[security.ALGORITHM],
        )
        if payload.get("type") != "refresh":
            raise credentials_exception

        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise credentials_exception

    # Issue a brand-new token pair
    new_access = security.create_access_token(data={"sub": user.email})
    new_refresh = security.create_refresh_token(data={"sub": user.email})
    return {"access_token": new_access, "refresh_token": new_refresh, "token_type": "bearer"}

# ... (End of standard endpoints) ...

# ✅ THE FIXED UPDATE ENDPOINT
@router.put("/me", response_model=UserResponse)
def update_user_me(
    user_update: UserUpdate, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(deps.get_current_user)
):
    # 1. Update Basic Info
    if user_update.first_name is not None: current_user.first_name = user_update.first_name
    if user_update.last_name is not None: current_user.last_name = user_update.last_name
    if user_update.location is not None: current_user.location = user_update.location
    if user_update.dob is not None: current_user.dob = user_update.dob
    
    # ✅ FIX: Explicitly Save Image URL
    # (Assuming your schema allows it. If not, this ensures the model updates)
    if hasattr(user_update, 'image_url') and user_update.image_url is not None:
        current_user.image_url = user_update.image_url

    # 2. Update Medical History
    if user_update.blood_type is not None: current_user.blood_type = user_update.blood_type
    if user_update.allergies is not None: current_user.allergies = user_update.allergies
    if user_update.chronic_conditions is not None: current_user.chronic_conditions = user_update.chronic_conditions
    if user_update.medications is not None: current_user.medications = user_update.medications
    if user_update.past_surgeries is not None: current_user.past_surgeries = user_update.past_surgeries

    # 3. Update Settings
    if user_update.settings_theme is not None: current_user.settings_theme = user_update.settings_theme
    if user_update.settings_notifications is not None: current_user.settings_notifications = user_update.settings_notifications
    if user_update.settings_email_updates is not None: current_user.settings_email_updates = user_update.settings_email_updates

    db.commit()
    db.refresh(current_user)
    return current_user

@router.get("/my-doctor-profile", response_model=DoctorResponse)
def get_my_doctor_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user)
):
    if current_user.role != "doctor":
        raise HTTPException(status_code=403, detail="Not a doctor")
    
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    if not doctor:
        # Create a default doctor profile if it doesn't exist but user is a doctor
        # This handles legacy users or sync issues
        doctor = Doctor(
            user_id=current_user.id,
            full_name=f"{current_user.first_name} {current_user.last_name}",
            specialty="General",
            license_number=f"TBD-{current_user.id}",
            is_verified=False,
            is_available=True,
            hourly_rate=5000.0,
            years_experience=0,
            bio="No bio yet."
        )
        db.add(doctor)
        db.commit()
        db.refresh(doctor)
        
    return doctor

# --- ✅ NEW: Verification Endpoints ---

@router.get("/verify-email", response_class=HTMLResponse)
def verify_email(token: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.verification_token == token).first()
    if not user:
        return HTMLResponse(content="<h1>Invalid or expired token</h1>", status_code=400)
    
    user.is_verified = True
    user.verification_token = None # Clear token
    db.commit()
    
    return HTMLResponse(content="""
        <html>
            <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                <h1 style="color: green;">Email Verified! ✅</h1>
                <p>Your account has been successfully verified.</p>
                <p>You can now close this window and log in to the app.</p>
            </body>
        </html>
    """)

@router.post("/admin/approve-doctor/{doctor_id}")
def approve_doctor(
    doctor_id: int, 
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    # In real app: current_user: User = Depends(deps.get_current_active_superuser)
):
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(404, detail="Doctor not found")
        
    user = db.query(User).filter(User.id == doctor.user_id).first()
    if not user:
        raise HTTPException(404, detail="User associated with doctor not found")

    # Approve
    doctor.status = "active"
    doctor.is_verified = True
    user.is_active = True
    
    db.commit()
    
    # Notify Doctor
    background_tasks.add_task(
        send_email,
        user.email,
        "Application Approved!",
        "Your doctor account is now active. You can log in."
    )
    
    return {"message": f"Doctor {doctor.full_name} approved"}

# --- 📲 FCM Device Token Registration ---

@router.patch("/me/device-token")
def update_device_token(
    body: DeviceTokenUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """Store the client's FCM device token for push notifications."""
    current_user.fcm_token = body.fcm_token
    db.commit()
    return {"message": "Device token updated"}


# --- ⚖️ Account Deactivation — NDPA 30-Day Legal Hold ---

@router.delete("/me/deactivate", status_code=status.HTTP_200_OK)
def deactivate_account(
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """
    Initiates a 30-day legal hold deletion per the Nigerian Data Protection Act (NDPA).

    Immediately:
      - Marks the account inactive so the user cannot log in.
      - Clears the FCM token so push notifications stop immediately.
      - Stamps deletion_requested_at with the current UTC time.

    After 30 days:
      - A scheduled scrubber (see scrub_expired_accounts below) will permanently
        anonymise all PII stored against this user record.
    """
    from datetime import timezone
    now_utc = datetime.now(timezone.utc)

    current_user.is_active = False
    current_user.fcm_token = None
    current_user.deletion_requested_at = now_utc

    db.commit()

    logger.info(
        f"[GDPR/NDPA] Deletion requested by user id={current_user.id} "
        f"email={current_user.email} at {now_utc.isoformat()}. "
        f"PII will be scrubbed after {now_utc.date()} + 30 days."
    )

    return {
        "message": (
            "Account deactivated. Your personal data will be permanently "
            "anonymized in 30 days per legal retention policies."
        )
    }


# ---------------------------------------------------------------------------
# 🧹 NDPA PII Scrubber — run this on a daily schedule
# ---------------------------------------------------------------------------
#
# HOW TO SCHEDULE:
#   Option A — Celery Beat (recommended for production on Render):
#       @celery_app.task
#       def run_scrubber():
#           from app.core.database import SessionLocal
#           db = SessionLocal()
#           try:
#               scrub_expired_accounts(db)
#           finally:
#               db.close()
#       # In celery beat schedule: run_scrubber every 24 h.
#
#   Option B — APScheduler (simpler, no Redis needed):
#       from apscheduler.schedulers.background import BackgroundScheduler
#       scheduler = BackgroundScheduler()
#       scheduler.add_job(run_scrubber, "interval", hours=24)
#       scheduler.start()
#       # Register startup/shutdown hooks in main.py.
#
# ---------------------------------------------------------------------------

def scrub_expired_accounts(db: Session) -> int:
    """
    Anonymises PII for all users who:
      - requested deletion (deletion_requested_at IS NOT NULL), AND
      - have been inactive for at least 30 days.

    NDPA-compliant scrambling:
      - email        → irreversible hash so uniqueness constraint is preserved
      - first/last   → "Deleted User"
      - password     → random bcrypt hash (account becomes permanently inaccessible)
      - location,    → None
        image_url,
        dob,
        blood_type,
        allergies,
        chronic_conditions,
        medications,
        past_surgeries
      - deletion_requested_at → None  (signals that scrub is complete)

    Returns the number of accounts scrubbed.
    """
    import uuid
    from datetime import timedelta, timezone
    from app.core import security as sec

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    # Fetch candidates inside the session — avoids loading all rows into memory
    candidates = (
        db.query(User)
        .filter(
            User.is_active == False,  # noqa: E712
            User.deletion_requested_at != None,  # noqa: E711
            User.deletion_requested_at <= cutoff,
        )
        .all()
    )

    scrubbed = 0
    for user in candidates:
        # Preserve a one-way reference so audit logs remain meaningful
        anon_tag = uuid.uuid4().hex[:12]

        user.email              = f"deleted_{anon_tag}@purged.invalid"
        user.first_name         = "Deleted"
        user.last_name          = "User"
        user.hashed_password    = sec.get_password_hash(uuid.uuid4().hex)
        user.dob                = None
        user.location           = None
        user.image_url          = None
        user.blood_type         = None
        user.allergies          = None
        user.chronic_conditions = None
        user.medications        = None
        user.past_surgeries     = None
        user.auth_provider      = None
        user.verification_token = None
        user.fcm_token          = None
        user.deletion_requested_at = None   # Marks scrub as complete

        scrubbed += 1
        logger.info(
            f"[NDPA SCRUBBER] PII anonymised for former user id={user.id} "
            f"(tag={anon_tag})."
        )

    if scrubbed:
        db.commit()

    logger.info(f"[NDPA SCRUBBER] Run complete. Accounts scrubbed: {scrubbed}")
    return scrubbed

