from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import EmailStr
from sqlalchemy.orm import Session
from datetime import date
from app.core.database import get_db
from app.models.user import User
from app.models.doctor import Doctor
from app.schemas.user import UserCreate, UserResponse, LoginRequest, Token, UserUpdate
from app.schemas.doctor import DoctorResponse, DoctorRegister
from app.core import security
from app.api import deps

router = APIRouter()

# --- 📧 HELPER: Mock Email Service ---
# --- 📧 REAL EMAIL SERVICE ---
import smtplib
import os
from email.message import EmailMessage

def send_email(to_email: str, subject: str, body: str):
    smtp_email = os.getenv("SMTP_EMAIL")
    smtp_password = os.getenv("SMTP_PASSWORD")

    if not smtp_email or not smtp_password:
        print("❌ SMTP Credentials Missing. Email NOT sent.")
        return

    try:
        msg = EmailMessage()
        msg.set_content(body)
        msg['Subject'] = subject
        msg['From'] = smtp_email
        msg['To'] = to_email

        # Gmail usually uses port 465 (SSL) or 587 (TLS)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(smtp_email, smtp_password)
            server.send_message(msg)
        
        print(f"✅ Email sent successfully to {to_email}")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")

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
        is_verified=False 
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    # ✅ Background Task: Send Verification Email
    verification_link = f"http://localhost:8000/api/v1/auth/verify-email?email={new_user.email}"
    background_tasks.add_task(
        send_email, 
        new_user.email, 
        "Verify your Mediq Account", 
        f"Click here to verify: {verification_link}"
    )

    return new_user

@router.post("/doctor/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register_doctor(doctor_in: DoctorRegister, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == doctor_in.email).first(): raise HTTPException(400, detail="Email registered")
    if db.query(Doctor).filter(Doctor.license_number == doctor_in.license_number).first(): raise HTTPException(400, detail="License registered")
    
    hashed_pwd = security.get_password_hash(doctor_in.password)
    names = doctor_in.full_name.split(" ")
    
    # ✅ Doctor user is INACTIVE initially
    new_user = User(
        email=doctor_in.email, 
        first_name=names[0], 
        last_name=names[-1] if len(names)>1 else "", 
        hashed_password=hashed_pwd, 
        role="doctor", 
        is_active=False, # Wait for Admin
        dob=date(1980, 1, 1), 
        location="Princeton-Plainsboro"
    )
    db.add(new_user)
    db.flush()

    new_doctor = Doctor(
        user_id=new_user.id, 
        full_name=doctor_in.full_name, 
        specialty=doctor_in.specialty, 
        license_number=doctor_in.license_number, 
        is_verified=False, 
        is_available=False, 
        hourly_rate=0.0,
        status="pending" # ✅ Pending State
    )
    db.add(new_doctor)
    db.commit()
    db.refresh(new_user)

    # ✅ Notify Admin
    background_tasks.add_task(
        send_email,
        "admin@mediq.com",
        "New Doctor Application",
        f"Dr. {doctor_in.full_name} has applied. License: {doctor_in.license_number}"
    )

    return new_user

@router.post("/login", response_model=Token)
def login(login_data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == login_data.email).first()
    if not user or not security.verify_password(login_data.password, user.hashed_password):
        raise HTTPException(401, detail="Incorrect email or password", headers={"WWW-Authenticate": "Bearer"})
    if not user.is_active:
        raise HTTPException(400, detail="Account is pending approval or inactive")
    return {"access_token": security.create_access_token(data={"sub": user.email}), "token_type": "bearer"}

@router.get("/me", response_model=UserResponse)
def read_users_me(current_user: User = Depends(deps.get_current_user)): return current_user

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

@router.get("/verify-email")
def verify_email(email: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(404, detail="User not found")
    
    user.is_verified = True
    db.commit()
    return {"message": "Email verified successfully"}

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
