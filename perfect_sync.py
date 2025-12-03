import os

# This script adds 'years_experience' and the Doctor Stats API.

files = {
    # ================= BACKEND =================

    # 1. Update Doctor Model (Add years_experience)
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
    years_experience = Column(Integer, default=1) # <--- NEW FIELD
    
    is_available = Column(Boolean, default=False)
    license_number = Column(String, unique=True, index=True)
    is_verified = Column(Boolean, default=False)
    documents_url = Column(String, nullable=True) 

    user = relationship("User")
""",

    # 2. Update Doctor Schema
    "backend/app/schemas/doctor.py": """
from pydantic import BaseModel, ConfigDict
from typing import Optional

class DoctorBase(BaseModel):
    full_name: str
    specialty: str
    bio: Optional[str] = None
    image_url: Optional[str] = None
    hourly_rate: float
    rating: float
    review_count: int
    years_experience: int # <--- NEW
    is_available: bool
    is_verified: bool

class DoctorResponse(DoctorBase):
    id: int
    user_id: int
    license_number: str 
    model_config = ConfigDict(from_attributes=True)

class DoctorRegister(BaseModel):
    email: str
    password: str
    full_name: str
    specialty: str
    license_number: str

class DoctorUpdate(BaseModel):
    bio: Optional[str] = None
    hourly_rate: Optional[float] = None
    years_experience: Optional[int] = None # <--- NEW
    image_url: Optional[str] = None
""",

    # 3. Update Doctor API (Add Stats Endpoint)
    "backend/app/api/v1/doctors.py": """
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.models.doctor import Doctor
from app.models.user import User
from app.models.appointment import Appointment
from app.schemas.doctor import DoctorResponse, DoctorUpdate
from app.api import deps

router = APIRouter()

@router.get("/", response_model=List[DoctorResponse])
def read_doctors(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return db.query(Doctor).filter(Doctor.is_verified == True).offset(skip).limit(limit).all()

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
    if data.hourly_rate: doctor.hourly_rate = data.hourly_rate
    if data.years_experience: doctor.years_experience = data.years_experience
    if data.image_url: doctor.image_url = data.image_url

    db.commit()
    db.refresh(doctor)
    return doctor

@router.get("/{doctor_id}", response_model=DoctorResponse)
def read_doctor(doctor_id: int, db: Session = Depends(get_db)):
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor: raise HTTPException(404, "Doctor not found")
    return doctor
""",

    # 4. Update Seeder (Add Years Exp)
    "backend/seed_doctors.py": """
import sys, os
from datetime import date
sys.path.append(os.getcwd())
from app.core.database import SessionLocal
from app.models.doctor import Doctor
from app.models.user import User
from app.core.security import get_password_hash

def seed():
    db = SessionLocal()
    if db.query(Doctor).first(): return
    
    docs = [
        {"email": "house@mediq.com", "name": "Dr. Gregory House", "spec": "Diagnostician", "lic": "MDCN-001", "rate": 5000.0, "exp": 15},
        {"email": "cuddy@mediq.com", "name": "Dr. Lisa Cuddy", "spec": "Endocrinologist", "lic": "MDCN-002", "rate": 4500.0, "exp": 12},
        {"email": "wilson@mediq.com", "name": "Dr. James Wilson", "spec": "Oncologist", "lic": "MDCN-003", "rate": 4800.0, "exp": 10},
    ]

    for d in docs:
        u = User(email=d["email"], first_name=d["name"].split()[0], last_name=d["name"].split()[-1], hashed_password=get_password_hash("password123"), role="doctor", dob=date(1980,1,1), location="Lagos")
        db.add(u)
        db.flush()
        doc = Doctor(user_id=u.id, full_name=d["name"], specialty=d["spec"], license_number=d["lic"], hourly_rate=d["rate"], years_experience=d["exp"], is_verified=True, is_available=True)
        db.add(doc)
    
    db.commit()
    print("Seeded Doctors with Experience Stats.")

if __name__ == "__main__": seed()
""",

    # ================= FRONTEND =================

    # 5. Update Doctor Model (Frontend)
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
  final int yearsExperience; // <--- NEW

  Doctor({
    required this.id, required this.fullName, required this.specialty, required this.imageUrl,
    required this.hourlyRate, required this.rating, required this.reviewCount, required this.isAvailable,
    this.bio, required this.isVerified, required this.yearsExperience
  });

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
      yearsExperience: json['years_experience'] ?? 0, // <--- NEW
    );
  }
}
""",

    # 6. Update Doctor Repository (Get Stats & Update Exp)
    "frontend/lib/src/features/doctors/data/doctor_repository.dart": """
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'doctor_model.dart';

final doctorRepositoryProvider = Provider<DoctorRepository>((ref) => DoctorRepository(ref.watch(dioProvider)));

class DoctorRepository {
  final Dio _dio;
  DoctorRepository(this._dio);

  Future<List<Doctor>> getDoctors() async {
    final response = await _dio.get('/api/v1/doctors/');
    return (response.data as List).map((json) => Doctor.fromJson(json)).toList();
  }

  Future<void> updateDoctorProfile({String? bio, double? hourlyRate, int? yearsExperience}) async {
    await _dio.put('/api/v1/doctors/me', data: {
      if (bio != null) "bio": bio,
      if (hourlyRate != null) "hourly_rate": hourlyRate,
      if (yearsExperience != null) "years_experience": yearsExperience
    });
  }

  Future<Map<String, dynamic>> getDoctorStats() async {
    final response = await _dio.get('/api/v1/doctors/stats');
    return response.data;
  }
  
  Future<void> createSlot({required int doctorId, required DateTime startTime}) async {
    await _dio.post('/api/v1/appointments/slots', data: {"doctor_id": doctorId, "start_time": startTime.toIso8601String()});
  }
}
""",

    # 7. Update Doctor Dashboard (Real Stats)
    "frontend/lib/src/features/doctor_dashboard/presentation/doctor_home_screen.dart": """
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:go_router/go_router.dart';
import 'package:mediq_app/src/features/auth/presentation/user_controller.dart';
import 'package:mediq_app/src/features/doctor_dashboard/presentation/doctor_requests_screen.dart';
import 'package:mediq_app/src/features/doctor_dashboard/presentation/doctor_profile_screen.dart';
import 'package:mediq_app/src/features/doctor_dashboard/presentation/doctor_schedule_screen.dart';
import 'package:mediq_app/src/features/doctor_dashboard/presentation/requests_controller.dart';
import 'package:mediq_app/src/features/doctors/data/doctor_repository.dart';

// --- NEW: Real Stats Provider ---
final doctorStatsProvider = FutureProvider.autoDispose((ref) async {
  return await ref.watch(doctorRepositoryProvider).getDoctorStats();
});

class DoctorHomeScreen extends ConsumerStatefulWidget {
  const DoctorHomeScreen({super.key});
  @override ConsumerState<DoctorHomeScreen> createState() => _DoctorHomeScreenState();
}

class _DoctorHomeScreenState extends ConsumerState<DoctorHomeScreen> {
  int _selectedIndex = 0;
  static const List<Widget> _pages = [_DoctorDashboardTab(), DoctorRequestsScreen(), DoctorScheduleScreen(), DoctorProfileScreen()];
  @override Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF9FAFB),
      body: SafeArea(child: IndexedStack(index: _selectedIndex, children: _pages)),
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _selectedIndex, onTap: (i) => setState(() => _selectedIndex = i),
        type: BottomNavigationBarType.fixed, backgroundColor: Colors.white, selectedItemColor: const Color(0xFF4A90E2), unselectedItemColor: Colors.grey[400],
        items: const [BottomNavigationBarItem(icon: Icon(Icons.dashboard_outlined), label: 'Overview'), BottomNavigationBarItem(icon: Icon(Icons.notifications_none), label: 'Requests'), BottomNavigationBarItem(icon: Icon(Icons.calendar_today_outlined), label: 'Schedule'), BottomNavigationBarItem(icon: Icon(Icons.person_outline), label: 'Profile')],
      ),
    );
  }
}

class _DoctorDashboardTab extends ConsumerWidget {
  const _DoctorDashboardTab();
  @override Widget build(BuildContext context, WidgetRef ref) {
    final userAsync = ref.watch(userProvider);
    final requestsAsync = ref.watch(requestsControllerProvider);
    final scheduleAsync = ref.watch(doctorScheduleProvider);
    final statsAsync = ref.watch(doctorStatsProvider); // REAL STATS

    return SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        userAsync.when(data: (user) => Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text("Good Morning,", style: TextStyle(color: Colors.grey[600])), Text("Dr. ${user.lastName}", style: const TextStyle(fontSize: 24, fontWeight: FontWeight.bold))]), IconButton(icon: const CircleAvatar(child: Icon(Icons.notifications)), onPressed: () => context.push('/notifications'))]), loading: () => const SizedBox(), error: (e,s)=>const SizedBox()),
        const SizedBox(height: 32),
        Row(children: [
          Expanded(child: _buildStatCard("Pending", requestsAsync.value?.length.toString() ?? "0", Icons.assignment_ind, Colors.orange)),
          const SizedBox(width: 16),
          Expanded(child: _buildStatCard("Upcoming", scheduleAsync.value?.length.toString() ?? "0", Icons.calendar_today, Colors.blue)),
        ]),
        const SizedBox(height: 16),
        statsAsync.when(
          data: (stats) => Row(children: [
            Expanded(child: _buildStatCard("Earnings", "₦${stats['earnings']}", Icons.payments, Colors.green)),
            const SizedBox(width: 16),
            Expanded(child: _buildStatCard("Rating", "${stats['rating']}", Icons.star, Colors.purple)),
          ]),
          loading: () => const LinearProgressIndicator(),
          error: (e,s) => const Text("Stats Error"),
        ),
      ]),
    );
  }

  Widget _buildStatCard(String title, String value, IconData icon, Color color) {
    return Container(padding: const EdgeInsets.all(20), decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(20), boxShadow: [BoxShadow(color: Colors.grey.withOpacity(0.1), blurRadius: 10)]), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Icon(icon, color: color, size: 24), const SizedBox(height: 12), Text(value, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold)), Text(title, style: TextStyle(fontSize: 12, color: Colors.grey))]));
  }
}
""",

    # 8. Update Doctor Edit Profile (Add Years Exp)
    "frontend/lib/src/features/doctor_dashboard/presentation/doctor_edit_profile_screen.dart": """
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:mediq_app/src/features/doctors/data/doctor_model.dart';
import 'package:mediq_app/src/features/doctors/data/doctor_repository.dart';

class DoctorEditProfileScreen extends ConsumerStatefulWidget {
  final Doctor doctor;
  const DoctorEditProfileScreen({super.key, required this.doctor});
  @override ConsumerState<DoctorEditProfileScreen> createState() => _DoctorEditProfileScreenState();
}

class _DoctorEditProfileScreenState extends ConsumerState<DoctorEditProfileScreen> {
  late TextEditingController _bioCtrl;
  late TextEditingController _rateCtrl;
  late TextEditingController _expCtrl; // NEW
  bool _isLoading = false;

  @override
  void initState() {
    super.initState();
    _bioCtrl = TextEditingController(text: widget.doctor.bio ?? "");
    _rateCtrl = TextEditingController(text: widget.doctor.hourlyRate.toString());
    _expCtrl = TextEditingController(text: widget.doctor.yearsExperience.toString());
  }

  Future<void> _handleSave() async {
    setState(() => _isLoading = true);
    try {
      await ref.read(doctorRepositoryProvider).updateDoctorProfile(
        bio: _bioCtrl.text.trim(),
        hourlyRate: double.tryParse(_rateCtrl.text.trim()),
        yearsExperience: int.tryParse(_expCtrl.text.trim()),
      );
      if (mounted) { ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Updated!"), backgroundColor: Colors.green)); context.pop(); }
    } catch (e) { if(mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("$e"), backgroundColor: Colors.red)); }
    finally { if(mounted) setState(() => _isLoading = false); }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text("Edit Profile"), backgroundColor: Colors.white, elevation: 0, foregroundColor: Colors.black),
      body: SingleChildScrollView(padding: const EdgeInsets.all(24), child: Column(children: [
        TextField(controller: _rateCtrl, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: "Rate (₦)", border: OutlineInputBorder(), prefixIcon: Icon(Icons.payments))),
        const SizedBox(height: 16),
        TextField(controller: _expCtrl, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: "Years Experience", border: OutlineInputBorder(), prefixIcon: Icon(Icons.work_history))),
        const SizedBox(height: 16),
        TextField(controller: _bioCtrl, maxLines: 5, decoration: const InputDecoration(labelText: "Bio", border: OutlineInputBorder())),
        const SizedBox(height: 32),
        SizedBox(width: double.infinity, height: 50, child: ElevatedButton(onPressed: _isLoading ? null : _handleSave, style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF4A90E2), foregroundColor: Colors.white), child: _isLoading ? const CircularProgressIndicator() : const Text("Save"))),
      ])),
    );
  }
}
""",
    
    # 9. Update Doctor Detail Screen (Show Real Experience)
    "frontend/lib/src/features/doctors/presentation/doctor_detail_screen.dart": """
import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:go_router/go_router.dart';
import '../../doctors/data/doctor_model.dart';

class DoctorDetailScreen extends StatelessWidget {
  final Doctor doctor;
  const DoctorDetailScreen({super.key, required this.doctor});

  @override
  Widget build(BuildContext context) {
    final statusColor = doctor.isAvailable ? Colors.green : Colors.grey;
    return Scaffold(
      body: CustomScrollView(slivers: [
        SliverAppBar(expandedHeight: 300, pinned: true, flexibleSpace: FlexibleSpaceBar(background: Image.network(doctor.imageUrl, fit: BoxFit.cover))),
        SliverToBoxAdapter(child: Padding(padding: const EdgeInsets.all(24), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
           Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
             Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
               Text(doctor.fullName, style: GoogleFonts.poppins(fontSize: 24, fontWeight: FontWeight.bold)),
               Text(doctor.specialty, style: GoogleFonts.lato(fontSize: 16, color: Colors.grey[600])),
             ]),
             Chip(label: Text("${doctor.rating} ★"), backgroundColor: Colors.amber.withOpacity(0.2))
           ]),
           const SizedBox(height: 24),
           Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
             _buildStat("Patients", "${doctor.reviewCount}+", Icons.people),
             _buildStat("Experience", "${doctor.yearsExperience} Yrs", Icons.work), // <--- REAL DATA
             _buildStat("Rating", "${doctor.rating}", Icons.star),
           ]),
           const SizedBox(height: 24),
           Text("About", style: GoogleFonts.poppins(fontSize: 18, fontWeight: FontWeight.bold)),
           Text(doctor.bio ?? "No bio.", style: GoogleFonts.lato(height: 1.5)),
        ]))),
      ]),
      bottomNavigationBar: SafeArea(child: Padding(padding: const EdgeInsets.all(16), child: ElevatedButton(
        onPressed: doctor.isAvailable ? () => context.push('/book_appointment', extra: doctor) : null,
        style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF4A90E2), foregroundColor: Colors.white, padding: const EdgeInsets.all(16)),
        child: Text("Book for ₦${doctor.hourlyRate.toInt()}", style: const TextStyle(fontSize: 18)),
      ))),
    );
  }

  Widget _buildStat(String label, String val, IconData icon) {
    return Column(children: [Icon(icon, color: const Color(0xFF4A90E2)), const SizedBox(height: 4), Text(val, style: const TextStyle(fontWeight: FontWeight.bold)), Text(label, style: const TextStyle(fontSize: 12, color: Colors.grey))]);
  }
}
"""
}

for path, content in files.items():
    full_path = path.replace("/", os.sep)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"✅ Synced: {path}")