import os

# This script adds 'has_review' logic, fixes Admin currency, and adds the Header Gradient.

files = {
    # ================= BACKEND =================

    # 1. Update Appointment Model (Link to Review)
    "backend/app/models/appointment.py": """
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Float
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base
from app.models.user import User 

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
    amount = Column(Float, default=0.0)
    commission = Column(Float, default=0.0)
    payout = Column(Float, default=0.0)

    patient = relationship("User")
    doctor = relationship("Doctor")
    slot = relationship("DoctorSlot", backref="appointment", uselist=False)
    # NEW: Link to review
    review = relationship("Review", back_populates="appointment", uselist=False)
""",

    # 2. Update Review Model (Link back to Appointment)
    "backend/app/models/review.py": """
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base

class Review(Base):
    __tablename__ = "reviews"
    id = Column(Integer, primary_key=True, index=True)
    appointment_id = Column(Integer, ForeignKey("appointments.id"), unique=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"))
    patient_id = Column(Integer, ForeignKey("users.id"))
    rating = Column(Integer)
    comment = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    doctor = relationship("Doctor")
    patient = relationship("User")
    # NEW: Link back
    appointment = relationship("Appointment", back_populates="review")
""",

    # 3. Update Appointment Schema (Add has_review bool)
    "backend/app/schemas/appointment.py": """
from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime

class SlotCreate(BaseModel):
    doctor_id: int
    start_time: datetime

class SlotResponse(BaseModel):
    id: int
    doctor_id: int
    start_time: datetime
    is_booked: bool
    model_config = ConfigDict(from_attributes=True)

class AppointmentCreate(BaseModel):
    slot_id: int
    notes: Optional[str] = None

class AppointmentResponse(BaseModel):
    id: int
    doctor_name: str
    status: str
    payment_status: str
    start_time: datetime
    notes: Optional[str] = None
    amount: float = 0.0
    has_review: bool = False # <--- NEW FIELD

    model_config = ConfigDict(from_attributes=True)

class GeneralBookRequest(BaseModel):
    notes: str
""",

    # 4. Update Appointment API (Populate has_review)
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
from app.models.review import Review
from app.schemas.appointment import SlotCreate, SlotResponse, AppointmentCreate, AppointmentResponse, GeneralBookRequest
from app.api import deps

router = APIRouter()

# ... (Helper to Map Response) ...
def map_appt(a, doc_name=None):
    d_name = doc_name if doc_name else (a.doctor.full_name if a.doctor else "Waiting...")
    s_time = a.slot.start_time if a.slot else a.start_time
    # CHECK IF REVIEW EXISTS
    has_rev = True if a.review else False
    return AppointmentResponse(
        id=a.id, doctor_name=d_name, status=a.status, 
        payment_status=a.payment_status, start_time=s_time, 
        notes=a.notes, amount=a.amount, has_review=has_rev
    )

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

@router.post("/book", response_model=AppointmentResponse, status_code=status.HTTP_201_CREATED)
def book_appointment(appt_data: AppointmentCreate, db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    slot = db.query(DoctorSlot).filter(DoctorSlot.id == appt_data.slot_id).first()
    if not slot or slot.is_booked: raise HTTPException(400, "Slot unavailable")
    slot.is_booked = True
    amount = slot.doctor.hourly_rate
    commission = amount * 0.30
    payout = amount - commission
    new_appt = Appointment(patient_id=current_user.id, doctor_id=slot.doctor_id, slot_id=slot.id, status="pending", payment_status="unpaid", notes=appt_data.notes, amount=amount, commission=commission, payout=payout)
    db.add(new_appt)
    db.commit()
    db.refresh(new_appt)
    return map_appt(new_appt)

@router.post("/book-general", response_model=AppointmentResponse, status_code=status.HTTP_201_CREATED)
def book_general_consultation(req: GeneralBookRequest, db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    doctor_payout = 1750.0
    patient_price = 2500.0 if current_user.plan == "premium" else 4000.0
    platform_commission = patient_price - doctor_payout
    new_appointment = Appointment(patient_id=current_user.id, doctor_id=None, slot_id=None, start_time=datetime.utcnow(), status="pending", payment_status="unpaid", notes=req.notes, amount=patient_price, commission=platform_commission, payout=doctor_payout)
    db.add(new_appointment)
    db.commit()
    db.refresh(new_appointment)
    return map_appt(new_appointment, "General Practitioner")

@router.get("/my", response_model=List[AppointmentResponse])
def get_my_appointments(db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    # Eager load review to avoid N+1
    scheduled = db.query(Appointment).options(joinedload(Appointment.review), joinedload(Appointment.slot)).join(DoctorSlot, Appointment.slot_id == DoctorSlot.id).filter(Appointment.patient_id == current_user.id).all()
    general = db.query(Appointment).options(joinedload(Appointment.review)).filter(Appointment.patient_id == current_user.id, Appointment.slot_id == None).all()
    results = [map_appt(a) for a in scheduled + general]
    results.sort(key=lambda x: x.start_time, reverse=True)
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
    if not doctor: raise HTTPException(403, "Not a doctor")
    appts = db.query(Appointment).options(joinedload(Appointment.patient)).join(DoctorSlot).filter(Appointment.doctor_id == doctor.id, Appointment.status == "pending", Appointment.payment_status == "paid").all()
    results = []
    for a in appts:
        a.patient_name = f"{a.patient.first_name} {a.patient.last_name}" if a.patient else "Unknown"
        results.append(AppointmentResponse(id=a.id, doctor_name=a.patient_name, status=a.status, payment_status=a.payment_status, start_time=a.slot.start_time, notes=a.notes, has_review=False))
    return results

@router.get("/doctor/queue", response_model=List[AppointmentResponse])
def get_general_queue(db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    if not doctor: raise HTTPException(403)
    appts = db.query(Appointment).options(joinedload(Appointment.patient)).filter(Appointment.doctor_id == None, Appointment.status == "pending", Appointment.payment_status == "paid").all()
    results = []
    for a in appts:
        # doctor_name field used for Patient Name in Doctor View
        p_name = f"{a.patient.first_name} {a.patient.last_name}" if a.patient else "Unknown"
        results.append(AppointmentResponse(id=a.id, doctor_name=p_name, status=a.status, payment_status=a.payment_status, start_time=a.start_time, notes=a.notes, has_review=False))
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
    return map_appt(appt, doctor.full_name)

@router.put("/doctor/appointments/{appt_id}/accept", response_model=AppointmentResponse)
def accept_appointment(appt_id: int, db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt: raise HTTPException(404)
    appt.status = "confirmed"
    db.commit()
    db.refresh(appt)
    return map_appt(appt, doctor.full_name)

@router.put("/doctor/appointments/{appt_id}/decline", response_model=AppointmentResponse)
def decline_appointment(appt_id: int, db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt: raise HTTPException(404)
    appt.status = "cancelled"
    if appt.slot: appt.slot.is_booked = False
    db.commit()
    db.refresh(appt)
    return map_appt(appt, doctor.full_name)

@router.put("/doctor/appointments/{appt_id}/cancel", response_model=AppointmentResponse)
def cancel_appointment_by_doctor(appt_id: int, db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt: raise HTTPException(404)
    appt.status = "cancelled"
    if appt.slot: appt.slot.is_booked = False
    db.commit()
    db.refresh(appt)
    return map_appt(appt, doctor.full_name)

@router.put("/doctor/appointments/{appt_id}/complete", response_model=AppointmentResponse)
def complete_appointment(appt_id: int, db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt: raise HTTPException(404)
    appt.status = "completed"
    db.commit()
    db.refresh(appt)
    return map_appt(appt, doctor.full_name)

@router.get("/doctor/appointments", response_model=List[AppointmentResponse])
def get_doctor_confirmed_appointments(db: Session = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
    scheduled = db.query(Appointment).options(joinedload(Appointment.patient), joinedload(Appointment.slot)).join(DoctorSlot, Appointment.slot_id == DoctorSlot.id).filter(Appointment.doctor_id == doctor.id, Appointment.status == "confirmed").all()
    general = db.query(Appointment).options(joinedload(Appointment.patient)).filter(Appointment.doctor_id == doctor.id, Appointment.slot_id == None, Appointment.status == "confirmed").all()
    
    results = []
    for a in scheduled + general:
        p_name = f"{a.patient.first_name} {a.patient.last_name}" if a.patient else "Unknown"
        start = a.slot.start_time if a.slot else a.start_time
        results.append(AppointmentResponse(id=a.id, doctor_name=p_name, status=a.status, payment_status=a.payment_status, start_time=start, notes=a.notes, has_review=False))
    results.sort(key=lambda x: x.start_time)
    return results
""",

    # ================= FRONTEND =================

    # 5. Update Frontend Appointment Model
    "frontend/lib/src/features/appointments/data/appointment_model.dart": """
class Appointment {
  final int id;
  final String doctorName;
  final String status;
  final String paymentStatus;
  final DateTime startTime;
  final String? notes;
  final double amount;
  final bool hasReview; // <--- NEW FIELD

  Appointment({
    required this.id,
    required this.doctorName,
    required this.status,
    required this.paymentStatus,
    required this.startTime,
    this.notes,
    this.amount = 0.0,
    this.hasReview = false, // Default false
  });

  factory Appointment.fromJson(Map<String, dynamic> json) {
    return Appointment(
      id: json['id'],
      doctorName: json['doctor_name'] ?? 'Unknown',
      status: json['status'],
      paymentStatus: json['payment_status'],
      startTime: DateTime.parse(json['start_time']),
      notes: json['notes'],
      amount: (json['amount'] as num?)?.toDouble() ?? 0.0,
      hasReview: json['has_review'] ?? false, // Parse it
    );
  }
}
""",

    # 6. Update Admin Dashboard (Currency Fix)
    "frontend/lib/src/features/admin/presentation/admin_dashboard.dart": """
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'package:mediq_app/src/features/auth/presentation/auth_controller.dart';
import 'package:mediq_app/src/features/auth/data/auth_repository.dart'; 
import 'package:mediq_app/src/features/content/data/content_repository.dart'; 
import 'package:mediq_app/src/features/admin/presentation/content/admin_content_editor.dart'; 

final adminStatsProvider = FutureProvider.autoDispose((ref) async {
  final dio = ref.watch(dioProvider);
  final response = await dio.get('/api/v1/admin/stats');
  return response.data;
});

final unverifiedDoctorsProvider = FutureProvider.autoDispose((ref) async {
  final dio = ref.watch(dioProvider);
  final response = await dio.get('/api/v1/doctors/'); 
  final List data = response.data;
  return data.where((d) => d['is_verified'] == false).toList();
});

final allUsersProvider = FutureProvider.autoDispose<List<User>>((ref) async {
  final dio = ref.watch(dioProvider);
  final response = await dio.get('/api/v1/admin/users');
  final List data = response.data;
  return data.map((json) => User.fromJson(json)).toList();
});

final adminContentProvider = FutureProvider.autoDispose((ref) async {
  return await ref.watch(contentRepositoryProvider).getHealthTips();
});

class AdminDashboard extends ConsumerStatefulWidget {
  const AdminDashboard({super.key});
  @override ConsumerState<AdminDashboard> createState() => _AdminDashboardState();
}

class _AdminDashboardState extends ConsumerState<AdminDashboard> {
  final TextEditingController _searchCtrl = TextEditingController();
  String _searchQuery = "";
  @override void dispose() { _searchCtrl.dispose(); super.dispose(); }

  Future<void> _verifyDoctor(int id) async {
    try { await ref.read(dioProvider).put('/api/v1/admin/doctors/$id/verify'); if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Doctor Verified"), backgroundColor: Colors.green)); ref.refresh(unverifiedDoctorsProvider); ref.refresh(adminStatsProvider); } catch (e) {}
  }
  Future<void> _rejectDoctor(int id) async {
    try { await ref.read(dioProvider).delete('/api/v1/admin/doctors/$id/reject'); if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Application Rejected"), backgroundColor: Colors.orange)); ref.refresh(unverifiedDoctorsProvider); } catch (e) {}
  }
  Future<void> _suspendUser(int id) async {
    try { await ref.read(dioProvider).put('/api/v1/admin/users/$id/suspend'); ref.refresh(allUsersProvider); if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("User Status Updated"), backgroundColor: Colors.blue)); } catch (e) {}
  }

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 4,
      child: Scaffold(
        backgroundColor: Colors.grey[100],
        appBar: AppBar(title: const Text("Admin Console", style: TextStyle(fontWeight: FontWeight.bold)), backgroundColor: Colors.blueGrey[900], foregroundColor: Colors.white,
          bottom: const TabBar(isScrollable: true, indicatorColor: Colors.orange, labelColor: Colors.white, unselectedLabelColor: Colors.white70, tabs: [Tab(icon: Icon(Icons.dashboard), text: "Overview"), Tab(icon: Icon(Icons.verified_user), text: "Verifications"), Tab(icon: Icon(Icons.people), text: "Users"), Tab(icon: Icon(Icons.article), text: "Content")]),
          actions: [IconButton(icon: const Icon(Icons.logout, color: Colors.redAccent), onPressed: () async { await ref.read(authControllerProvider.notifier).logout(); if(context.mounted) context.go('/auth'); })],
        ),
        body: TabBarView(children: [_buildOverviewTab(), _buildDoctorsTab(), _buildUsersTab(), _buildContentTab()]),
        floatingActionButton: FloatingActionButton(backgroundColor: Colors.orange, child: const Icon(Icons.add), onPressed: () async { final result = await Navigator.push(context, MaterialPageRoute(builder: (_) => const AdminContentEditorScreen())); if (result == true) ref.refresh(adminContentProvider); }),
      ),
    );
  }

  Widget _buildOverviewTab() {
    final statsAsync = ref.watch(adminStatsProvider);
    return statsAsync.when(
      loading: () => const Center(child: CircularProgressIndicator()), error: (e, _) => Center(child: Text("Error: $e")),
      data: (stats) => SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text("System Health", style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
          const SizedBox(height: 16),
          Wrap(spacing: 16, runSpacing: 16, children: [
            _StatCard(title: "Total Revenue", value: "NGN ${stats['total_revenue']}", color: Colors.green, icon: Icons.attach_money), // FIXED CURRENCY
            _StatCard(title: "Pending Docs", value: "${stats['pending_verifications']}", color: Colors.orange, icon: Icons.warning_amber),
            _StatCard(title: "Total Users", value: "${stats['total_users']}", color: Colors.blue, icon: Icons.person),
            _StatCard(title: "Total Doctors", value: "${stats['total_doctors']}", color: Colors.teal, icon: Icons.medical_services),
            _StatCard(title: "Active Appts", value: "${stats['active_appointments']}", color: Colors.purple, icon: Icons.calendar_today),
          ]),
        ]),
      ),
    );
  }
  
  Widget _buildDoctorsTab() {
    final docsAsync = ref.watch(unverifiedDoctorsProvider);
    return docsAsync.when(loading: () => const Center(child: CircularProgressIndicator()), error: (e, _) => Center(child: Text("Error: $e")), data: (doctors) => doctors.isEmpty ? const Center(child: Text("No pending verifications.")) : ListView.builder(padding: const EdgeInsets.all(16), itemCount: doctors.length, itemBuilder: (ctx, i) => Card(child: ListTile(leading: const CircleAvatar(child: Icon(Icons.local_hospital)), title: Text(doctors[i]['full_name']), subtitle: Text("License: ${doctors[i]['license_number']}"), trailing: Row(mainAxisSize: MainAxisSize.min, children: [IconButton(icon: const Icon(Icons.close, color: Colors.red), onPressed: () => _rejectDoctor(doctors[i]['id'])), IconButton(icon: const Icon(Icons.check, color: Colors.green), onPressed: () => _verifyDoctor(doctors[i]['id']))])))));
  }

  Widget _buildUsersTab() {
    final usersAsync = ref.watch(allUsersProvider);
    return Column(children: [
      Container(padding: const EdgeInsets.all(16), color: Colors.white, child: TextField(controller: _searchCtrl, decoration: InputDecoration(hintText: "Search...", prefixIcon: const Icon(Icons.search), border: OutlineInputBorder(borderRadius: BorderRadius.circular(12))), onChanged: (val) => setState(() => _searchQuery = val.toLowerCase()))),
      Expanded(child: usersAsync.when(loading: () => const Center(child: CircularProgressIndicator()), error: (e, _) => Center(child: Text("Error: $e")), data: (users) {
          final filtered = users.where((u) => u.fullName.toLowerCase().contains(_searchQuery.toLowerCase()) || u.email.toLowerCase().contains(_searchQuery)).toList();
          if (filtered.isEmpty) return const Center(child: Text("No users found."));
          return ListView.builder(itemCount: filtered.length, padding: const EdgeInsets.all(16), itemBuilder: (ctx, i) {
              final user = filtered[i];
              if (user.role == 'admin') return ListTile(title: Text(user.fullName), subtitle: const Text("ADMIN"));
              return Card(color: user.isBanned ? Colors.red[50] : Colors.white, child: ListTile(leading: CircleAvatar(backgroundColor: user.isBanned ? Colors.red : (user.role == 'doctor' ? Colors.blue : Colors.green), child: Icon(user.isBanned ? Icons.block : Icons.person, color: Colors.white)), title: Text(user.fullName, style: TextStyle(decoration: user.isBanned ? TextDecoration.lineThrough : null)), subtitle: Text("${user.email} • ${user.role.toUpperCase()}"), trailing: ElevatedButton(onPressed: () => _suspendUser(user.id), style: ElevatedButton.styleFrom(backgroundColor: user.isBanned ? Colors.green : Colors.red, foregroundColor: Colors.white), child: Text(user.isBanned ? "Unsuspend" : "Suspend"))));
            });
        })),
    ]);
  }

  Widget _buildContentTab() {
    final contentAsync = ref.watch(adminContentProvider);
    return contentAsync.when(loading: () => const Center(child: CircularProgressIndicator()), error: (e, _) => Text("$e"), data: (tips) => ListView.builder(itemCount: tips.length, padding: const EdgeInsets.all(16), itemBuilder: (ctx, i) => Card(margin: const EdgeInsets.only(bottom: 12), child: ListTile(title: Text(tips[i].title), trailing: Row(mainAxisSize: MainAxisSize.min, children: [IconButton(icon: const Icon(Icons.edit, color: Colors.blue), onPressed: () async { final result = await Navigator.push(context, MaterialPageRoute(builder: (_) => AdminContentEditorScreen(healthTip: tips[i]))); if (result == true) ref.refresh(adminContentProvider); }), IconButton(icon: const Icon(Icons.delete, color: Colors.red), onPressed: () async { await ref.read(contentRepositoryProvider).deleteHealthTip(tips[i].id); ref.refresh(adminContentProvider); })])))));
  }
}

class _StatCard extends StatelessWidget {
  final String title, value; final Color color; final IconData icon;
  const _StatCard({required this.title, required this.value, required this.color, required this.icon});
  @override Widget build(BuildContext context) {
    final width = (MediaQuery.of(context).size.width - 48) / 2;
    return Container(width: width, padding: const EdgeInsets.all(16), decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(12), border: Border(left: BorderSide(color: color, width: 4)), boxShadow: [BoxShadow(color: Colors.grey.withOpacity(0.1), blurRadius: 5)]), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Icon(icon, color: color, size: 32), const SizedBox(height: 12), Text(value, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold)), Text(title, style: TextStyle(fontSize: 12, color: Colors.grey[600]))]));
  }
}
""",

    # 7. Home Widgets (Update Header Gradient)
    "frontend/lib/src/features/patient_dashboard/presentation/widgets/home_widgets.dart": """
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';
import 'package:mediq_app/src/features/appointments/data/appointment_repository.dart';
import 'package:mediq_app/src/features/auth/presentation/user_controller.dart';
import 'package:mediq_app/src/features/appointments/data/appointment_model.dart';

final nextAppointmentProvider = FutureProvider.autoDispose<Appointment?>((ref) async {
  final appointments = await ref.watch(appointmentRepositoryProvider).getMyAppointments();
  final upcoming = appointments.where((a) => a.status == 'confirmed' && a.startTime.isAfter(DateTime.now())).toList();
  if (upcoming.isEmpty) return null;
  upcoming.sort((a, b) => a.startTime.compareTo(b.startTime));
  return upcoming.first;
});

class HomeHeader extends StatelessWidget {
  final String userName;
  const HomeHeader({super.key, required this.userName});
  @override
  Widget build(BuildContext context) {
    return Container(
      // --- GRADIENT FADE FIX ---
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topCenter, end: Alignment.bottomCenter,
          colors: [Colors.white.withOpacity(0.8), const Color(0xFFF9FAFB)],
          stops: const [0.0, 1.0],
        ),
      ),
      padding: const EdgeInsets.symmetric(vertical: 16),
      child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
        Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text("Welcome Back,", style: TextStyle(fontSize: 16, color: Colors.grey[600], fontWeight: FontWeight.w500)),
          const SizedBox(height: 4),
          Text(userName, style: const TextStyle(fontSize: 28, fontWeight: FontWeight.bold, color: Color(0xFF1A1A1A), letterSpacing: -0.5)),
        ]),
        GestureDetector(onTap: () => context.push('/notifications'), child: Container(padding: const EdgeInsets.all(12), decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(16), border: Border.all(color: Colors.grey.withOpacity(0.1)), boxShadow: [BoxShadow(color: const Color(0xFF4A90E2).withOpacity(0.1), blurRadius: 15, offset: const Offset(0, 5))]), child: const Icon(Icons.notifications_none_rounded, color: Color(0xFF4A90E2), size: 26))),
      ]),
    );
  }
}
// ... (Rest of AppointmentCard and QuickActionGrid remains the same as previous version)
class AppointmentCard extends ConsumerWidget {
  const AppointmentCard({super.key});
  @override Widget build(BuildContext context, WidgetRef ref) {
    final nextApptAsync = ref.watch(nextAppointmentProvider);
    return nextApptAsync.when(loading: () => const SizedBox(height: 140), error: (e, _) => const SizedBox(), data: (appointment) {
      if (appointment == null) return Container(width: double.infinity, padding: const EdgeInsets.all(24), decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(32), border: Border.all(color: Colors.grey.withOpacity(0.1))), child: Row(children: [Container(padding: const EdgeInsets.all(12), decoration: BoxDecoration(color: const Color(0xFF4A90E2).withOpacity(0.1), shape: BoxShape.circle), child: const Icon(Icons.calendar_today, color: Color(0xFF4A90E2))), const SizedBox(width: 16), Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [const Text("No upcoming visits", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)), const SizedBox(height: 4), Text("Book a doctor to get started.", style: TextStyle(fontSize: 12, color: Colors.grey[600]))])), TextButton(onPressed: () => context.push('/find_doctor'), child: const Text("Book", style: TextStyle(fontWeight: FontWeight.bold)))]));
      final dateStr = DateFormat('MMM dd, yyyy').format(appointment.startTime);
      final timeStr = DateFormat('jm').format(appointment.startTime);
      return Container(width: double.infinity, padding: const EdgeInsets.all(24), decoration: BoxDecoration(borderRadius: BorderRadius.circular(32), gradient: const LinearGradient(colors: [Color(0xFF4A90E2), Color(0xFF00CEC9)]), boxShadow: [BoxShadow(color: const Color(0xFF4A90E2).withOpacity(0.4), blurRadius: 25, offset: const Offset(0, 10))]), child: Column(children: [Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [Container(padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6), decoration: BoxDecoration(color: Colors.white.withOpacity(0.2), borderRadius: BorderRadius.circular(12)), child: Row(children: [const Icon(Icons.calendar_today_rounded, color: Colors.white, size: 14), const SizedBox(width: 6), Text("$dateStr • $timeStr", style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 12))])), const Icon(Icons.videocam, color: Colors.white70)]), const SizedBox(height: 20), Row(children: [Container(decoration: BoxDecoration(shape: BoxShape.circle, border: Border.all(color: Colors.white.withOpacity(0.5), width: 2)), child: const CircleAvatar(radius: 26, backgroundColor: Colors.white24, child: Icon(Icons.person, color: Colors.white, size: 28))), const SizedBox(width: 16), Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(appointment.doctorName, style: const TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.bold)), const SizedBox(height: 4), const Text("Video Consultation", style: TextStyle(color: Colors.white70, fontSize: 14))]))])]));
    });
  }
}
class QuickActionGrid extends ConsumerWidget {
  const QuickActionGrid({super.key});
  void _showBookingOptions(BuildContext context, WidgetRef ref) {
    final userAsync = ref.watch(userProvider);
    String priceText = "Loading...";
    double priceVal = 4000.0;
    userAsync.whenData((user) { if (user.plan == 'premium') { priceText = "NGN 2,500 (Premium)"; priceVal = 2500.0; } else { priceText = "NGN 4,000 (Standard)"; priceVal = 4000.0; } });
    showModalBottomSheet(context: context, backgroundColor: Colors.transparent, builder: (ctx) => Container(padding: const EdgeInsets.all(24), decoration: const BoxDecoration(color: Colors.white, borderRadius: BorderRadius.vertical(top: Radius.circular(24))), child: Column(mainAxisSize: MainAxisSize.min, children: [ListTile(title: const Text("See a GP Now", style: TextStyle(fontWeight: FontWeight.bold)), subtitle: Text(priceText), leading: const Icon(Icons.flash_on, color: Colors.orange), onTap: () async { Navigator.pop(ctx); try { final appt = await ref.read(appointmentRepositoryProvider).bookGeneralConsultation("I need a doctor now."); if (context.mounted) context.push('/payment', extra: {'appointment': appt, 'amount': priceVal}); } catch (e) { if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("Error: $e"), backgroundColor: Colors.red)); } }), const Divider(), ListTile(title: const Text("Book a Specialist"), leading: const Icon(Icons.calendar_month, color: Color(0xFF4A90E2)), onTap: () { Navigator.pop(ctx); context.push('/find_doctor'); })])));
  }
  @override Widget build(BuildContext context, WidgetRef ref) {
    final actions = [{'icon': Icons.chat_bubble_outline_rounded, 'label': 'Check Symptoms', 'color': 0xFF4A90E2}, {'icon': Icons.person_search_rounded, 'label': 'Find Doctor', 'color': 0xFF00CEC9}, {'icon': Icons.local_pharmacy_outlined, 'label': 'Pharmacy', 'color': 0xFFFF7675}, {'icon': Icons.phone_in_talk, 'label': 'Emergency', 'color': 0xFFFDCB6E}];
    return GridView.builder(shrinkWrap: true, physics: const NeverScrollableScrollPhysics(), gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(crossAxisCount: 2, childAspectRatio: 1.3, crossAxisSpacing: 16, mainAxisSpacing: 16), itemCount: actions.length, itemBuilder: (context, index) { final item = actions[index]; final color = Color(item['color'] as int); return InkWell(onTap: () { if (index == 0) context.push('/chat'); else if (index == 1) _showBookingOptions(context, ref); else if (index == 3) context.push('/emergency'); else ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("${item['label']} coming soon!"))); }, borderRadius: BorderRadius.circular(24), child: Container(padding: const EdgeInsets.all(12), decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(24), boxShadow: [BoxShadow(color: Colors.grey.withOpacity(0.05), blurRadius: 20, offset: const Offset(0, 5))]), child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [Container(padding: const EdgeInsets.all(10), decoration: BoxDecoration(color: color.withOpacity(0.1), shape: BoxShape.circle), child: Icon(item['icon'] as IconData, color: color, size: 22)), const SizedBox(height: 8), Text(item['label'] as String, textAlign: TextAlign.center, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 13, color: Color(0xFF2D3436))) ]))); });
  }
}
"""
}

for path, content in files.items():
    full_path = path.replace("/", os.sep)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"✅ Polished: {path}")