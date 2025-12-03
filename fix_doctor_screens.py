import os

# This script creates the missing screens for the Doctor features.

files = {
    # 1. Doctor Repository (Ensures update/createSlot methods exist)
    "frontend/lib/src/features/doctors/data/doctor_repository.dart": """
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'doctor_model.dart';

final doctorRepositoryProvider = Provider<DoctorRepository>((ref) {
  return DoctorRepository(ref.watch(dioProvider));
});

class DoctorRepository {
  final Dio _dio;
  DoctorRepository(this._dio);

  Future<List<Doctor>> getDoctors() async {
    try {
      final response = await _dio.get('/api/v1/doctors/');
      return (response.data as List).map((json) => Doctor.fromJson(json)).toList();
    } catch (e) { throw Exception('Failed to fetch doctors: $e'); }
  }

  Future<void> updateDoctorProfile({String? bio, double? hourlyRate}) async {
    try {
      await _dio.put('/api/v1/doctors/me', data: {if (bio != null) "bio": bio, if (hourlyRate != null) "hourly_rate": hourlyRate});
    } catch (e) { throw Exception('Failed to update profile'); }
  }

  Future<void> createSlot({required int doctorId, required DateTime startTime}) async {
    try {
      await _dio.post('/api/v1/appointments/slots', data: {"doctor_id": doctorId, "start_time": startTime.toIso8601String()});
    } catch (e) { throw Exception('Failed to create slot'); }
  }
}
""",

    # 2. Doctor Edit Profile Screen
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
  bool _isLoading = false;

  @override
  void initState() {
    super.initState();
    _bioCtrl = TextEditingController(text: widget.doctor.bio ?? "");
    _rateCtrl = TextEditingController(text: widget.doctor.hourlyRate.toString());
  }

  Future<void> _handleSave() async {
    setState(() => _isLoading = true);
    try {
      await ref.read(doctorRepositoryProvider).updateDoctorProfile(bio: _bioCtrl.text.trim(), hourlyRate: double.tryParse(_rateCtrl.text.trim()));
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Profile Updated!"), backgroundColor: Colors.green));
        context.pop();
      }
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("Error: $e"), backgroundColor: Colors.red));
    } finally { if (mounted) setState(() => _isLoading = false); }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text("Edit Profile"), backgroundColor: Colors.white, elevation: 0, foregroundColor: Colors.black),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Column(children: [
          TextField(controller: _rateCtrl, keyboardType: const TextInputType.numberWithOptions(decimal: true), decoration: const InputDecoration(labelText: "Hourly Rate (\$)", border: OutlineInputBorder())),
          const SizedBox(height: 24),
          TextField(controller: _bioCtrl, maxLines: 5, decoration: const InputDecoration(labelText: "Biography", border: OutlineInputBorder())),
          const SizedBox(height: 40),
          SizedBox(width: double.infinity, height: 50, child: ElevatedButton(onPressed: _isLoading ? null : _handleSave, style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF4A90E2), foregroundColor: Colors.white), child: _isLoading ? const CircularProgressIndicator(color: Colors.white) : const Text("Save Changes"))),
        ]),
      ),
    );
  }
}
""",

    # 3. Doctor Availability Screen
    "frontend/lib/src/features/doctor_dashboard/presentation/doctor_availability_screen.dart": """
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:mediq_app/src/features/doctors/data/doctor_repository.dart';
import 'package:mediq_app/src/features/auth/data/auth_repository.dart';

final myDoctorProfileProvider = FutureProvider.autoDispose((ref) async { return await ref.watch(authRepositoryProvider).getMyDoctorProfile(); });

class DoctorAvailabilityScreen extends ConsumerStatefulWidget {
  const DoctorAvailabilityScreen({super.key});
  @override ConsumerState<DoctorAvailabilityScreen> createState() => _DoctorAvailabilityScreenState();
}

class _DoctorAvailabilityScreenState extends ConsumerState<DoctorAvailabilityScreen> {
  DateTime _selectedDate = DateTime.now().add(const Duration(days: 1));
  final List<int> _standardHours = [9, 10, 11, 12, 13, 14, 15, 16, 17];
  bool _isCreating = false;

  Future<void> _addSlot(int hour, int doctorId) async {
    setState(() => _isCreating = true);
    try {
      final slotTime = DateTime(_selectedDate.year, _selectedDate.month, _selectedDate.day, hour, 0);
      await ref.read(doctorRepositoryProvider).createSlot(doctorId: doctorId, startTime: slotTime);
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("Slot added for ${DateFormat('h:mm a').format(slotTime)}"), backgroundColor: Colors.green));
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("Failed: $e"), backgroundColor: Colors.red));
    } finally { if (mounted) setState(() => _isCreating = false); }
  }

  @override
  Widget build(BuildContext context) {
    final doctorAsync = ref.watch(myDoctorProfileProvider);
    return Scaffold(
      appBar: AppBar(title: const Text("Manage Availability"), backgroundColor: Colors.white, foregroundColor: Colors.black, elevation: 0),
      body: doctorAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text("Error: $e")),
        data: (doctor) => Padding(
          padding: const EdgeInsets.all(16.0),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            InkWell(
              onTap: () async { final d = await showDatePicker(context: context, initialDate: _selectedDate, firstDate: DateTime.now(), lastDate: DateTime.now().add(const Duration(days: 30))); if(d!=null) setState(()=>_selectedDate=d); },
              child: Container(padding: const EdgeInsets.all(12), decoration: BoxDecoration(border: Border.all(color: Colors.grey), borderRadius: BorderRadius.circular(12)), child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [Text(DateFormat('EEE, MMM d').format(_selectedDate), style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold)), const Icon(Icons.calendar_today, color: Color(0xFF4A90E2))])),
            ),
            const SizedBox(height: 24),
            const Text("Tap to add a slot:", style: TextStyle(fontWeight: FontWeight.bold)),
            const SizedBox(height: 12),
            Wrap(spacing: 12, runSpacing: 12, children: _standardHours.map((h) => ActionChip(label: Text(DateFormat('h:mm a').format(DateTime(2023,1,1,h))), onPressed: _isCreating ? null : () => _addSlot(h, doctor.id), avatar: const Icon(Icons.add, size: 16, color: Color(0xFF4A90E2)))).toList()),
          ]),
        ),
      ),
    );
  }
}
""",

    # 4. Doctor Profile Screen (Ensures wiring is correct)
    "frontend/lib/src/features/doctor_dashboard/presentation/doctor_profile_screen.dart": """
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:mediq_app/src/features/auth/data/auth_repository.dart';
import 'package:mediq_app/src/features/auth/presentation/auth_controller.dart';

final myDoctorProfileProvider = FutureProvider.autoDispose((ref) async {
  return await ref.watch(authRepositoryProvider).getMyDoctorProfile();
});

class DoctorProfileScreen extends ConsumerWidget {
  const DoctorProfileScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final doctorAsync = ref.watch(myDoctorProfileProvider);

    return doctorAsync.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => Center(child: Text("Error: $e")),
      data: (doctor) {
        return ListView(
          padding: const EdgeInsets.all(24),
          children: [
            Center(child: Column(children: [
              CircleAvatar(radius: 50, backgroundImage: NetworkImage(doctor.imageUrl), onBackgroundImageError: (_,__) => const Icon(Icons.person)),
              const SizedBox(height: 16),
              Text(doctor.fullName, style: const TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
              Text(doctor.specialty, style: TextStyle(color: Colors.grey[600])),
            ])),
            const SizedBox(height: 32),
            ListTile(leading: const Icon(Icons.edit_outlined), title: const Text("Edit Public Profile"), trailing: const Icon(Icons.chevron_right), onTap: () => context.push('/doctor_edit_profile', extra: doctor)),
            const Divider(),
            ListTile(leading: const Icon(Icons.calendar_month_outlined), title: const Text("Manage Availability"), trailing: const Icon(Icons.chevron_right), onTap: () => context.push('/doctor_availability')),
            const Divider(),
            ListTile(leading: const Icon(Icons.logout, color: Colors.red), title: const Text("Logout", style: TextStyle(color: Colors.red)), onTap: () async { await ref.read(authControllerProvider.notifier).logout(); if (context.mounted) context.go('/auth'); }),
          ],
        );
      },
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