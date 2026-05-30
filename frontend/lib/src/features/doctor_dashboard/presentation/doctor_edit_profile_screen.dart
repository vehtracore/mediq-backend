import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';
import 'package:mediq_app/src/features/chat/data/image_upload_service.dart';
import 'package:mediq_app/src/features/doctors/data/doctor_model.dart';
import 'package:mediq_app/src/features/doctors/data/doctor_repository.dart';
import 'package:mediq_app/src/features/auth/data/auth_repository.dart';

class DoctorEditProfileScreen extends ConsumerStatefulWidget {
  final Doctor doctor;
  const DoctorEditProfileScreen({super.key, required this.doctor});
  @override
  ConsumerState<DoctorEditProfileScreen> createState() =>
      _DoctorEditProfileScreenState();
}

class _DoctorEditProfileScreenState
    extends ConsumerState<DoctorEditProfileScreen> {
  late TextEditingController _bioCtrl;
  late TextEditingController _rateCtrl;
  late TextEditingController _expCtrl;
  bool _isLoading = false;
  XFile? _selectedImage;
  Uint8List? _webImageBytes;

  @override
  void initState() {
    super.initState();
    _bioCtrl = TextEditingController(text: widget.doctor.bio ?? "");
    _rateCtrl =
        TextEditingController(text: widget.doctor.hourlyRate.toString());
    _expCtrl =
        TextEditingController(text: widget.doctor.yearsExperience.toString());
  }

  Future<void> _pickImage() async {
    final picker = ImagePicker();
    final pickedFile = await picker.pickImage(
      source: ImageSource.gallery,
      imageQuality: 90,
      maxWidth: 1920,
      maxHeight: 1920,
    );

    if (pickedFile != null) {
      final bytes = await pickedFile.readAsBytes();
      setState(() {
        _selectedImage = pickedFile;
        _webImageBytes = bytes;
      });
    }
  }

  Future<void> _handleSave() async {
    setState(() => _isLoading = true);
    try {
      String? uploadedImageUrl;
      if (_selectedImage != null) {
        uploadedImageUrl = await ref
            .read(imageUploadServiceProvider)
            .uploadFile(_selectedImage!);
      }

      // Update DOCTOR Profile
      await ref.read(doctorRepositoryProvider).updateDoctorProfile(
            bio: _bioCtrl.text.trim(),
            hourlyRate: double.tryParse(_rateCtrl.text.trim()),
            yearsExperience: int.tryParse(_expCtrl.text.trim()),
            imageUrl: uploadedImageUrl,
          );
      
      // Update USER Profile (For persistence fallback)
      if (uploadedImageUrl != null) {
        // Need to import AuthRepository at top if not present
        // Actually we can read provider directly
        await ref.read(authRepositoryProvider).updateUser(imageUrl: uploadedImageUrl);
      }
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text("Updated!"), backgroundColor: Colors.green));
        context.pop();
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text("$e"), backgroundColor: Colors.red));
      }
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    ImageProvider? backgroundImage;
    if (_webImageBytes != null) {
      backgroundImage = MemoryImage(_webImageBytes!);
    } else if (widget.doctor.imageUrl.isNotEmpty) {
      backgroundImage = NetworkImage(widget.doctor.imageUrl);
    }

    return Scaffold(
      appBar: AppBar(
          title: const Text("Edit Profile"),
          backgroundColor: Colors.white,
          elevation: 0,
          foregroundColor: Colors.black),
      body: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(children: [
            Center(
              child: Stack(
                children: [
                  CircleAvatar(
                    radius: 50,
                    backgroundColor: Colors.grey[200],
                    backgroundImage: backgroundImage,
                    child: (backgroundImage == null)
                        ? const CircleAvatar(
                            backgroundColor: Colors.transparent,
                            child: Icon(Icons.person),
                          )
                        : null,
                  ),
                  Positioned(
                    bottom: 0,
                    right: 0,
                    child: GestureDetector(
                      onTap: _pickImage,
                      child: Container(
                        padding: const EdgeInsets.all(8),
                        decoration: const BoxDecoration(
                          color: Color(0xFF4A90E2),
                          shape: BoxShape.circle,
                        ),
                        child: const Icon(Icons.camera_alt,
                            color: Colors.white, size: 20),
                      ),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 32),
            TextField(
                controller: _rateCtrl,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                    labelText: "Rate (₦)",
                    border: OutlineInputBorder(),
                    prefixIcon: Icon(Icons.payments))),
            const SizedBox(height: 16),
            TextField(
                controller: _expCtrl,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                    labelText: "Years Experience",
                    border: OutlineInputBorder(),
                    prefixIcon: Icon(Icons.work_history))),
            const SizedBox(height: 16),
            TextField(
                controller: _bioCtrl,
                maxLines: 5,
                decoration: const InputDecoration(
                    labelText: "Bio", border: OutlineInputBorder())),
            const SizedBox(height: 32),
            SizedBox(
                width: double.infinity,
                height: 50,
                child: ElevatedButton(
                    onPressed: _isLoading ? null : _handleSave,
                    style: ElevatedButton.styleFrom(
                        backgroundColor: const Color(0xFF4A90E2),
                        foregroundColor: Colors.white),
                    child: _isLoading
                        ? const CircularProgressIndicator()
                        : const Text("Save"))),
          ])),
    );
  }
}
