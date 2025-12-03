import os

# This script restores the MedIQ project to a known good state.
# It overwrites backend and frontend files with the final, corrected code.

files = {
    # ==========================================
    # BACKEND (FastAPI)
    # ==========================================

    "backend/app/models/user.py": """
from sqlalchemy import Column, Integer, String, Boolean, Date
from app.core.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    first_name = Column(String, index=True)
    last_name = Column(String, index=True)
    dob = Column(Date)
    location = Column(String, nullable=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    role = Column(String, default="patient") 
    is_active = Column(Boolean, default=True)
    is_banned = Column(Boolean, default=False)
""",

    "backend/app/models/doctor.py": """
from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base

class Doctor(Base):
    __tablename__ = "doctors"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    full_name = Column(String, index=True)
    specialty = Column(String, index=True)
    bio = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    hourly_rate = Column(Float, default=0.0)
    rating = Column(Float, default=5.0)
    review_count = Column(Integer, default=0)
    is_available = Column(Boolean, default=True)
    license_number = Column(String, unique=True, index=True)
    is_verified = Column(Boolean, default=False)
    documents_url = Column(String, nullable=True) 

    user = relationship("User")
""",

    "backend/app/models/appointment.py": """
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base
from app.models.user import User # Fix circular ref

class DoctorSlot(Base):
    __tablename__ = "doctor_slots"
    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"))
    start_time = Column(DateTime, index=True)
    is_booked = Column(Boolean, default=False)
    doctor = relationship("Doctor", backref="slots")

class Appointment(Base):
    __tablename__ = "appointments"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("users.id"))
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    slot_id = Column(Integer, ForeignKey("doctor_slots.id"), unique=True, nullable=True)
    start_time = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="pending")
    payment_status = Column(String, default="unpaid")
    notes = Column(String, nullable=True)
    related_appointment_id = Column(Integer, nullable=True)

    patient = relationship("User")
    doctor = relationship("Doctor")
    slot = relationship("DoctorSlot", backref="appointment", uselist=False)
""",

    "backend/app/api/v1/auth.py": """
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
""",

    "backend/app/api/v1/appointments.py": """
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from typing import List
from datetime import datetime
from pydantic import BaseModel
from app.core.database import get_db
from app.models.appointment import Appointment, DoctorSlot
from app.models.doctor import Doctor
from app.models.user import User
from app.schemas.appointment import SlotCreate, SlotResponse, AppointmentCreate, AppointmentResponse
from app.api import deps

router = APIRouter()
class GeneralBookRequest(BaseModel): notes: str

@router.post("/slots", response_model=SlotResponse, status_code=status.HTTP_201_CREATED)
def create_slot(slot: SlotCreate, db: Session = Depends(get_db)):
    new_slot = DoctorSlot(doctor_id=slot.doctor_id, start_time=slot.start_time, is_booked=False)
    db.add(new_slot)
    db.commit()
    db.refresh(new_slot)
    return new_slot

@router.get("/doctors/{doctor_id}/slots", response_model=List[SlotResponse])
def get_doctor_slots(doctor_id: int, db: Session = Depends(get_db)):
    return db.query(DoctorSlot).filter(DoctorSlot.doctor_id == doctor_id, DoctorSlot.is_booked == False).order_by(DoctorSlot.start_time).all()

@router.post("/book", response_model=AppointmentResponse, status_code=status.HTTP_201_CREATED)
def book_appointment(appt_data: AppointmentCreate, db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    slot = db.query(DoctorSlot).filter(DoctorSlot.id == appt_data.slot_id).first()
    if not slot or slot.is_booked: raise HTTPException(400, detail="Slot unavailable")
    slot.is_booked = True
    new_appt = Appointment(patient_id=current_user.id, doctor_id=slot.doctor_id, slot_id=slot.id, status="pending", payment_status="unpaid", notes=appt_data.notes)
    db.add(new_appt)
    db.commit()
    db.refresh(new_appt)
    return AppointmentResponse(id=new_appt.id, doctor_name=new_appt.doctor.full_name, status=new_appt.status, payment_status=new_appt.payment_status, start_time=slot.start_time, notes=new_appt.notes)

@router.get("/my", response_model=List[AppointmentResponse])
def get_my_appointments(db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    scheduled = db.query(Appointment).join(DoctorSlot, Appointment.slot_id == DoctorSlot.id).filter(Appointment.patient_id == current_user.id).all()
    general = db.query(Appointment).filter(Appointment.patient_id == current_user.id, Appointment.slot_id == None).all()
    results = []
    for a in scheduled + general:
        doc = a.doctor.full_name if a.doctor else "Waiting for Doctor..."
        start = a.slot.start_time if a.slot else a.start_time
        results.append(AppointmentResponse(id=a.id, doctor_name=doc, status=a.status, payment_status=a.payment_status, start_time=start, notes=a.notes))
    results.sort(key=lambda x: x.start_time, reverse=True)
    return results

@router.put("/{appt_id}/pay", response_model=AppointmentResponse)
def pay_appointment(appt_id: int, db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt: raise HTTPException(404, detail="Not found")
    if appt.patient_id != current_user.id: raise HTTPException(403, detail="Not authorized")
    appt.payment_status = "paid"
    db.commit()
    db.refresh(appt)
    doc = appt.doctor.full_name if appt.doctor else "Waiting for Doctor..."
    start = appt.slot.start_time if appt.slot else appt.start_time
    return AppointmentResponse(id=appt.id, doctor_name=doc, status=appt.status, payment_status=appt.payment_status, start_time=start, notes=appt.notes)

@router.post("/book-general", response_model=AppointmentResponse)
def book_general(req: GeneralBookRequest, db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    new_appt = Appointment(patient_id=current_user.id, doctor_id=None, slot_id=None, start_time=datetime.utcnow(), status="pending", payment_status="unpaid", notes=req.notes)
    db.add(new_appt)
    db.commit()
    db.refresh(new_appt)
    return AppointmentResponse(id=new_appt.id, doctor_name="Waiting for Doctor...", status=new_appt.status, payment_status=new_appt.payment_status, start_time=new_appt.start_time, notes=new_appt.notes)

# DOCTOR
@router.get("/doctor/requests", response_model=List[AppointmentResponse])
def get_doctor_requests(db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    if not doctor: raise HTTPException(403)
    appts = db.query(Appointment).join(DoctorSlot).filter(Appointment.doctor_id == doctor.id, Appointment.status == "pending", Appointment.payment_status == "paid").all()
    results = []
    for a in appts:
        results.append(AppointmentResponse(id=a.id, doctor_name=doctor.full_name, status=a.status, payment_status=a.payment_status, start_time=a.slot.start_time, notes=a.notes))
    return results

@router.get("/doctor/queue", response_model=List[AppointmentResponse])
def get_general_queue(db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    if not doctor: raise HTTPException(403)
    appts = db.query(Appointment).options(joinedload(Appointment.patient)).filter(Appointment.doctor_id == None, Appointment.status == "pending", Appointment.payment_status == "paid").all()
    results = []
    for a in appts:
        results.append(AppointmentResponse(id=a.id, doctor_name="Unassigned", status=a.status, payment_status=a.payment_status, start_time=a.start_time, notes=a.notes))
    return results

@router.put("/doctor/appointments/{appt_id}/accept", response_model=AppointmentResponse)
def accept_appt(appt_id: int, db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    appt.status = "confirmed"
    db.commit()
    db.refresh(appt)
    return AppointmentResponse(id=appt.id, doctor_name=doctor.full_name, status=appt.status, payment_status=appt.payment_status, start_time=appt.slot.start_time, notes=appt.notes)

@router.put("/doctor/appointments/{appt_id}/decline", response_model=AppointmentResponse)
def decline_appt(appt_id: int, db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    appt.status = "cancelled"
    if appt.slot: appt.slot.is_booked = False
    db.commit()
    db.refresh(appt)
    return AppointmentResponse(id=appt.id, doctor_name=doctor.full_name, status=appt.status, payment_status=appt.payment_status, start_time=appt.slot.start_time, notes=appt.notes)

@router.put("/doctor/queue/{appt_id}/claim", response_model=AppointmentResponse)
def claim_appt(appt_id: int, db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    appt = db.query(Appointment).filter(Appointment.id == appt_id, Appointment.doctor_id == None).first()
    appt.doctor_id = doctor.id
    appt.status = "confirmed"
    db.commit()
    db.refresh(appt)
    return AppointmentResponse(id=appt.id, doctor_name=doctor.full_name, status=appt.status, payment_status=appt.payment_status, start_time=appt.start_time, notes=appt.notes)
    
@router.get("/doctor/appointments", response_model=List[AppointmentResponse])
def get_confirmed(db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    scheduled = db.query(Appointment).join(DoctorSlot).filter(Appointment.doctor_id == doctor.id, Appointment.status == "confirmed").all()
    general = db.query(Appointment).filter(Appointment.doctor_id == doctor.id, Appointment.slot_id == None, Appointment.status == "confirmed").all()
    results = []
    for a in scheduled + general:
        start = a.slot.start_time if a.slot else a.start_time
        results.append(AppointmentResponse(id=a.id, doctor_name=doctor.full_name, status=a.status, payment_status=a.payment_status, start_time=start, notes=a.notes))
    results.sort(key=lambda x: x.start_time)
    return results
""",

    # ==========================================
    # FRONTEND (Flutter)
    # ==========================================

    "frontend/lib/src/features/doctors/data/doctor_model.dart": """
class Doctor {
  final int id;
  final String fullName;
  final String specialty;
  final String imageUrl;
  final double hourlyRate;
  final double rating;
  final int reviewCount;
  final bool isAvailable;
  final String? bio;
  final bool isVerified; 

  Doctor({required this.id, required this.fullName, required this.specialty, required this.imageUrl, required this.hourlyRate, required this.rating, required this.reviewCount, required this.isAvailable, this.bio, required this.isVerified});

  factory Doctor.fromJson(Map<String, dynamic> json) {
    return Doctor(
      id: json['id'],
      fullName: json['full_name'],
      specialty: json['specialty'],
      imageUrl: json['image_url'] ?? 'https://i.pravatar.cc/150',
      hourlyRate: (json['hourly_rate'] as num).toDouble(),
      rating: (json['rating'] as num).toDouble(),
      reviewCount: json['review_count'],
      isAvailable: json['is_available'] ?? false,
      bio: json['bio'],
      isVerified: json['is_verified'] ?? false, 
    );
  }
}
""",

    "frontend/lib/src/features/appointments/data/appointment_repository.dart": """
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'slot_model.dart';
import 'appointment_model.dart';

final appointmentRepositoryProvider = Provider<AppointmentRepository>((ref) {
  return AppointmentRepository(ref.watch(dioProvider));
});

class AppointmentRepository {
  final Dio _dio;
  AppointmentRepository(this._dio);

  Future<List<DoctorSlot>> getSlots(int doctorId) async {
    final response = await _dio.get('/api/v1/appointments/doctors/$doctorId/slots');
    return (response.data as List).map((json) => DoctorSlot.fromJson(json)).toList();
  }

  Future<Appointment> bookSlot({required int slotId, required String notes}) async {
    final response = await _dio.post('/api/v1/appointments/book', data: {"slot_id": slotId, "notes": notes});
    return Appointment.fromJson(response.data);
  }

  Future<List<Appointment>> getMyAppointments() async {
    final response = await _dio.get('/api/v1/appointments/my');
    return (response.data as List).map((json) => Appointment.fromJson(json)).toList();
  }

  Future<void> markAsPaid(int appointmentId) async {
    await _dio.put('/api/v1/appointments/$appointmentId/pay');
  }
  
  Future<void> cancelMyAppointment(int id) async {
    await _dio.put('/api/v1/appointments/$id/cancel');
  }

  Future<Appointment> bookGeneralConsultation(String notes) async {
    final response = await _dio.post('/api/v1/appointments/book-general', data: {'notes': notes});
    return Appointment.fromJson(response.data);
  }

  // Doctor
  Future<List<Appointment>> getDoctorRequests() async {
    final response = await _dio.get('/api/v1/appointments/doctor/requests');
    return (response.data as List).map((json) => Appointment.fromJson(json)).toList();
  }
  Future<List<Appointment>> getGeneralQueue() async {
    final response = await _dio.get('/api/v1/appointments/doctor/queue');
    return (response.data as List).map((json) => Appointment.fromJson(json)).toList();
  }
  Future<List<Appointment>> getDoctorConfirmedAppointments() async {
    final response = await _dio.get('/api/v1/appointments/doctor/appointments');
    return (response.data as List).map((json) => Appointment.fromJson(json)).toList();
  }
  Future<void> acceptAppointment(int id) async { await _dio.put('/api/v1/appointments/doctor/appointments/$id/accept'); }
  Future<void> declineAppointment(int id) async { await _dio.put('/api/v1/appointments/doctor/appointments/$id/decline'); }
  Future<void> cancelAppointmentByDoctor(int id) async { await _dio.put('/api/v1/appointments/doctor/appointments/$id/cancel'); }
  Future<void> claimAppointment(int id) async { await _dio.put('/api/v1/appointments/doctor/queue/$id/claim'); }
}
""",

    "frontend/lib/src/features/auth/auth_screen.dart": """
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';
import 'presentation/auth_controller.dart';
import 'presentation/user_controller.dart';
import 'data/auth_repository.dart';

class AuthScreen extends ConsumerStatefulWidget {
  const AuthScreen({super.key});
  @override ConsumerState<AuthScreen> createState() => _AuthScreenState();
}

class _AuthScreenState extends ConsumerState<AuthScreen> {
  bool _isLogin = true;
  final _firstNameController = TextEditingController();
  final _lastNameController = TextEditingController();
  final _locationController = TextEditingController();
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  DateTime? _selectedDate;
  bool _agreedToTerms = false;
  final _formKey = GlobalKey<FormState>();

  Future<void> _handleSubmit() async {
    if (!_formKey.currentState!.validate()) return;
    final controller = ref.read(authControllerProvider.notifier);
    if (_isLogin) {
      await controller.login(email: _emailController.text.trim(), password: _passwordController.text.trim());
    } else {
      if (_selectedDate == null || !_agreedToTerms) return;
      await controller.signUp(firstName: _firstNameController.text.trim(), lastName: _lastNameController.text.trim(), location: _locationController.text.trim(), dob: _selectedDate!, email: _emailController.text.trim(), password: _passwordController.text.trim());
    }
  }

  @override
  Widget build(BuildContext context) {
    final authState = ref.watch(authControllerProvider);
    ref.listen<AsyncValue<void>>(authControllerProvider, (previous, next) async {
      if (!next.isLoading && !next.hasError) {
        try {
          final user = await ref.refresh(userProvider.future);
          if (!mounted) return;
          if (user.role == 'admin') context.go('/admin_dashboard');
          else if (user.role == 'doctor') {
             try {
               final doctor = await ref.read(authRepositoryProvider).getMyDoctorProfile();
               if (doctor.isVerified) context.go('/doctor_home');
               else context.go('/doctor_pending');
             } catch (e) { context.go('/doctor_pending'); }
          }
          else context.go('/patient_home');
        } catch (e) { context.go('/patient_home'); }
      }
    });

    return Scaffold(
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24.0),
          child: Form(
            key: _formKey,
            child: Column(
              children: [
                const Icon(Icons.health_and_safety, size: 64, color: Color(0xFF4A90E2)),
                const SizedBox(height: 24),
                Text(_isLogin ? "Welcome Back" : "Create Profile", style: Theme.of(context).textTheme.headlineMedium),
                const SizedBox(height: 32),
                if (!_isLogin) ...[
                   Row(children: [Expanded(child: TextFormField(controller: _firstNameController, decoration: const InputDecoration(labelText: "First Name"))), const SizedBox(width: 12), Expanded(child: TextFormField(controller: _lastNameController, decoration: const InputDecoration(labelText: "Last Name")))]),
                   const SizedBox(height: 16),
                   Row(children: [Expanded(child: InkWell(onTap: () async { final d = await showDatePicker(context: context, initialDate: DateTime(2000), firstDate: DateTime(1900), lastDate: DateTime.now()); if(d!=null) setState(() => _selectedDate = d); }, child: InputDecorator(decoration: const InputDecoration(labelText: "DOB"), child: Text(_selectedDate == null ? "Select" : DateFormat('yyyy-MM-dd').format(_selectedDate!))))), const SizedBox(width: 12), Expanded(child: TextFormField(controller: _locationController, decoration: const InputDecoration(labelText: "City")))]),
                   const SizedBox(height: 16),
                ],
                TextFormField(controller: _emailController, decoration: const InputDecoration(labelText: "Email")),
                const SizedBox(height: 16),
                TextFormField(controller: _passwordController, obscureText: true, decoration: const InputDecoration(labelText: "Password")),
                if (!_isLogin) ...[const SizedBox(height: 24), CheckboxListTile(value: _agreedToTerms, onChanged: (v) => setState(() => _agreedToTerms = v!), title: const Text("I agree to Terms"))],
                const SizedBox(height: 32),
                SizedBox(width: double.infinity, height: 50, child: ElevatedButton(onPressed: authState.isLoading ? null : _handleSubmit, child: authState.isLoading ? const CircularProgressIndicator() : Text(_isLogin ? "Login" : "Sign Up"))),
                TextButton(onPressed: () => setState(() => _isLogin = !_isLogin), child: Text(_isLogin ? "Sign Up" : "Login")),
                const Divider(),
                TextButton(onPressed: () => context.push('/doctor_register'), child: const Text("Are you a Doctor? Apply here")),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
""",

    "frontend/lib/src/features/splash/splash_screen.dart": """
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:mediq_app/src/core/storage/storage_service.dart';
import 'package:mediq_app/src/features/auth/presentation/user_controller.dart';
import 'package:mediq_app/src/features/auth/data/auth_repository.dart';

class SplashScreen extends ConsumerStatefulWidget {
  const SplashScreen({super.key});
  @override ConsumerState<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends ConsumerState<SplashScreen> {
  @override void initState() { super.initState(); _checkSession(); }

  Future<void> _checkSession() async {
    await Future.delayed(const Duration(seconds: 2));
    final token = await ref.read(storageServiceProvider).getToken();
    if (token != null && token.isNotEmpty) {
      try {
        final user = await ref.read(userProvider.future);
        if (!mounted) return;
        if (user.role == 'doctor') {
           try {
            final doctor = await ref.read(authRepositoryProvider).getMyDoctorProfile();
            if (doctor.isVerified) context.go('/doctor_home');
            else context.go('/doctor_pending');
           } catch (e) { context.go('/doctor_pending'); }
        } else if (user.role == 'admin') { context.go('/admin_dashboard'); }
        else { context.go('/patient_home'); }
      } catch (e) { context.go('/auth'); }
    } else { context.go('/onboarding'); }
  }

  @override
  Widget build(BuildContext context) {
    return const Scaffold(backgroundColor: Color(0xFF4A90E2), body: Center(child: CircularProgressIndicator(color: Colors.white)));
  }
}
""",

    "frontend/lib/src/features/doctor_dashboard/presentation/doctor_home_screen.dart": """
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/features/auth/presentation/user_controller.dart';
import 'package:mediq_app/src/features/doctor_dashboard/presentation/doctor_requests_screen.dart';
import 'package:mediq_app/src/features/doctor_dashboard/presentation/doctor_profile_screen.dart';
import 'package:mediq_app/src/features/doctor_dashboard/presentation/doctor_schedule_screen.dart';
import 'package:mediq_app/src/features/doctor_dashboard/presentation/doctor_edit_profile_screen.dart'; 
import 'package:mediq_app/src/features/doctor_dashboard/presentation/doctor_availability_screen.dart';
import 'package:go_router/go_router.dart';

class DoctorHomeScreen extends ConsumerStatefulWidget {
  const DoctorHomeScreen({super.key});
  @override ConsumerState<DoctorHomeScreen> createState() => _DoctorHomeScreenState();
}

class _DoctorHomeScreenState extends ConsumerState<DoctorHomeScreen> {
  int _selectedIndex = 0;
  static const List<Widget> _pages = [
    _DoctorDashboardTab(),
    DoctorRequestsScreen(),
    DoctorScheduleScreen(),
    DoctorProfileScreen(),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF9FAFB),
      body: SafeArea(child: IndexedStack(index: _selectedIndex, children: _pages)),
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _selectedIndex,
        onTap: (i) => setState(() => _selectedIndex = i),
        type: BottomNavigationBarType.fixed,
        selectedItemColor: const Color(0xFF4A90E2),
        unselectedItemColor: Colors.grey,
        items: const [
          BottomNavigationBarItem(icon: Icon(Icons.dashboard_outlined), label: 'Overview'),
          BottomNavigationBarItem(icon: Icon(Icons.notifications_none), label: 'Requests'),
          BottomNavigationBarItem(icon: Icon(Icons.calendar_today_outlined), label: 'Schedule'),
          BottomNavigationBarItem(icon: Icon(Icons.person_outline), label: 'Profile'),
        ],
      ),
    );
  }
}

class _DoctorDashboardTab extends ConsumerWidget {
  const _DoctorDashboardTab();
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final userAsync = ref.watch(userProvider);
    return SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          userAsync.when(
            data: (user) => Text("Welcome, Dr. ${user.lastName}", style: const TextStyle(fontSize: 24, fontWeight: FontWeight.bold)),
            loading: () => const SizedBox(), error: (e, s) => const SizedBox()
          ),
          const SizedBox(height: 32),
          const Text("Your Stats", style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
          // Add stats widgets here
        ],
      ),
    );
  }
}
"""
}

for path, content in files.items():
    full_path = path.replace("/", os.sep)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"✅ Fixed: {path}")