
from fastapi import APIRouter, Depends, HTTPException, status
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

@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(user: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.email == user.email).first()
    if db_user: raise HTTPException(400, detail="Email already registered")
    hashed_pwd = security.get_password_hash(user.password)
    new_user = User(email=user.email, first_name=user.first_name, last_name=user.last_name, dob=user.dob, location=user.location, hashed_password=hashed_pwd, role=user.role)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

@router.post("/doctor/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register_doctor(doctor_in: DoctorRegister, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == doctor_in.email).first(): raise HTTPException(400, detail="Email registered")
    if db.query(Doctor).filter(Doctor.license_number == doctor_in.license_number).first(): raise HTTPException(400, detail="License registered")
    
    hashed_pwd = security.get_password_hash(doctor_in.password)
    names = doctor_in.full_name.split(" ")
    new_user = User(email=doctor_in.email, first_name=names[0], last_name=names[-1] if len(names)>1 else "", hashed_password=hashed_pwd, role="doctor", is_active=True, dob=date(1980, 1, 1), location="Princeton-Plainsboro")
    db.add(new_user)
    db.flush()

    new_doctor = Doctor(user_id=new_user.id, full_name=doctor_in.full_name, specialty=doctor_in.specialty, license_number=doctor_in.license_number, is_verified=False, is_available=False, hourly_rate=0.0)
    db.add(new_doctor)
    db.commit()
    db.refresh(new_user)
    return new_user

@router.post("/login", response_model=Token)
def login(login_data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == login_data.email).first()
    if not user or not security.verify_password(login_data.password, user.hashed_password):
        raise HTTPException(401, detail="Incorrect email or password", headers={"WWW-Authenticate": "Bearer"})
    return {"access_token": security.create_access_token(data={"sub": user.email}), "token_type": "bearer"}

@router.get("/me", response_model=UserResponse)
def read_users_me(current_user: User = Depends(deps.get_current_user)): return current_user

@router.put("/me", response_model=UserResponse)
def update_user_me(user_update: UserUpdate, db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    if user_update.first_name: current_user.first_name = user_update.first_name
    if user_update.last_name: current_user.last_name = user_update.last_name
    if user_update.location: current_user.location = user_update.location
    if user_update.dob: current_user.dob = user_update.dob
    db.commit()
    db.refresh(current_user)
    return current_user

@router.get("/my-doctor-profile", response_model=DoctorResponse)
def get_my_doctor_profile(db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    if current_user.role != "doctor": raise HTTPException(403, detail="Access restricted")
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    if not doctor: raise HTTPException(404, detail="Doctor profile not found")
    return doctor
