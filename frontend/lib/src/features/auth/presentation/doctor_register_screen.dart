import 'dart:io'; // Needed for File (Mobile only)
import 'package:flutter/foundation.dart'; // Needed for kIsWeb check
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:image_picker/image_picker.dart';
import 'package:mediq_app/src/features/auth/data/auth_repository.dart';
import 'package:mediq_app/src/features/media/data/media_repository.dart';

class DoctorRegisterScreen extends ConsumerStatefulWidget {
  const DoctorRegisterScreen({super.key});

  @override
  ConsumerState<DoctorRegisterScreen> createState() =>
      _DoctorRegisterScreenState();
}

class _DoctorRegisterScreenState extends ConsumerState<DoctorRegisterScreen> {
  final _formKey = GlobalKey<FormState>();
  bool _isLoading = false;

  final _fullNameCtrl = TextEditingController();
  final _emailCtrl = TextEditingController();
  final _passwordCtrl = TextEditingController();

  // CHANGED: Use XFile (Cross-Platform) instead of File
  XFile? _licenseImage;

  String? _selectedSpecialty;
  final List<String> _specialties = [
    "General Practitioner",
    "Cardiologist",
    "Neurologist",
    "Pediatrician",
    "Surgeon",
    "Psychiatrist",
    "Dermatologist",
    "Oncologist",
    "Diagnostician",
  ];

  @override
  void dispose() {
    _fullNameCtrl.dispose();
    _emailCtrl.dispose();
    _passwordCtrl.dispose();
    super.dispose();
  }

  // --- Image Picker Logic (Web Safe) ---
  Future<void> _pickLicenseImage() async {
    final picker = ImagePicker();
    final XFile? pickedFile = await picker.pickImage(
      source: ImageSource.gallery,
      imageQuality: 80, // Optimize size
    );

    if (pickedFile != null) {
      setState(() {
        _licenseImage = pickedFile; // Store as XFile
      });
    }
  }

  Future<void> _handleSubmit() async {
    if (!_formKey.currentState!.validate()) return;

    if (_licenseImage == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text("Please upload your Medical License image"),
          backgroundColor: Colors.red,
        ),
      );
      return;
    }

    setState(() => _isLoading = true);

    try {
      // 1. Upload Image (Repo handles Web/Mobile logic)
      final String licenseUrl = await ref
          .read(mediaRepositoryProvider)
          .uploadFile(_licenseImage!, folder: "mdq_plus/doctors/licenses");

      // 2. Register Doctor
      await ref
          .read(authRepositoryProvider)
          .registerDoctor(
            fullName: _fullNameCtrl.text.trim(),
            email: _emailCtrl.text.trim(),
            password: _passwordCtrl.text.trim(),
            specialty: _selectedSpecialty!,
            licenseNumber: licenseUrl, // Save URL to DB
          );

      if (!mounted) return;

      // 3. Success Dialog
      showDialog(
        context: context,
        barrierDismissible: false,
        builder: (ctx) => AlertDialog(
          title: const Text("Application Submitted"),
          content: const Text(
            "Your license has been uploaded and profile created. "
            "Waiting for Admin verification.",
          ),
          actions: [
            TextButton(
              onPressed: () {
                Navigator.pop(ctx);
                context.go('/auth');
              },
              child: const Text("OK"),
            ),
          ],
        ),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text("Error: $e"), backgroundColor: Colors.red),
      );
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    // Helper to get the correct ImageProvider based on platform
    ImageProvider? imageProvider;
    if (_licenseImage != null) {
      if (kIsWeb) {
        // Web: Use NetworkImage for Blob URLs
        imageProvider = NetworkImage(_licenseImage!.path);
      } else {
        // Mobile: Use FileImage for disk paths
        imageProvider = FileImage(File(_licenseImage!.path));
      }
    }

    return Scaffold(
      backgroundColor: Colors.white,
      appBar: AppBar(
        title: const Text("Doctor Registration"),
        backgroundColor: Colors.white,
        elevation: 0,
        foregroundColor: Colors.black,
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24.0),
        child: Form(
          key: _formKey,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _buildTextField("Full Name", _fullNameCtrl, Icons.person),
              const SizedBox(height: 16),
              _buildTextField("Email", _emailCtrl, Icons.email),
              const SizedBox(height: 16),
              _buildTextField(
                "Password",
                _passwordCtrl,
                Icons.lock,
                isPassword: true,
              ),
              const SizedBox(height: 16),
              DropdownButtonFormField<String>(
                value: _selectedSpecialty,
                hint: const Text("Select Specialty"),
                items: _specialties
                    .map((s) => DropdownMenuItem(value: s, child: Text(s)))
                    .toList(),
                onChanged: (v) => setState(() => _selectedSpecialty = v),
                validator: (v) => v == null ? "Required" : null,
                decoration: InputDecoration(
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(12),
                  ),
                  prefixIcon: const Icon(Icons.work_outline),
                ),
              ),
              const SizedBox(height: 24),

              // --- Upload Widget ---
              const Text(
                "Medical License",
                style: TextStyle(fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 8),
              GestureDetector(
                onTap: _pickLicenseImage,
                child: Container(
                  height: 150,
                  width: double.infinity,
                  decoration: BoxDecoration(
                    color: Colors.grey[100],
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: Colors.grey[300]!),
                    image: imageProvider != null
                        ? DecorationImage(
                            image: imageProvider,
                            fit: BoxFit.cover,
                          )
                        : null,
                  ),
                  child: _licenseImage == null
                      ? const Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Icon(
                              Icons.cloud_upload_outlined,
                              size: 40,
                              color: Colors.grey,
                            ),
                            SizedBox(height: 8),
                            Text(
                              "Tap to upload License Image",
                              style: TextStyle(color: Colors.grey),
                            ),
                          ],
                        )
                      : null,
                ),
              ),
              const SizedBox(height: 32),

              SizedBox(
                height: 50,
                child: ElevatedButton(
                  onPressed: _isLoading ? null : _handleSubmit,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF4A90E2),
                    foregroundColor: Colors.white,
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                  ),
                  child: _isLoading
                      ? const CircularProgressIndicator(color: Colors.white)
                      : const Text("Submit Application"),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildTextField(
    String label,
    TextEditingController ctrl,
    IconData icon, {
    bool isPassword = false,
  }) {
    return TextFormField(
      controller: ctrl,
      obscureText: isPassword,
      decoration: InputDecoration(
        labelText: label,
        prefixIcon: Icon(icon),
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
      ),
      validator: (v) => v!.isEmpty ? "Required" : null,
    );
  }
}
