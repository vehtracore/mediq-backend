
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
