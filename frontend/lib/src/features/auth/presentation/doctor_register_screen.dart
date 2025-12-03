import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:mediq_app/src/features/auth/data/auth_repository.dart'; // Import Repo directly

class DoctorRegisterScreen extends ConsumerStatefulWidget {
  const DoctorRegisterScreen({super.key});

  @override
  ConsumerState<DoctorRegisterScreen> createState() =>
      _DoctorRegisterScreenState();
}

class _DoctorRegisterScreenState extends ConsumerState<DoctorRegisterScreen> {
  final _formKey = GlobalKey<FormState>();
  bool _isLoading = false; // Local state management

  // Controllers
  final _fullNameCtrl = TextEditingController();
  final _emailCtrl = TextEditingController();
  final _passwordCtrl = TextEditingController();
  final _licenseCtrl = TextEditingController();

  // Dropdown State
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
    _licenseCtrl.dispose();
    super.dispose();
  }

  Future<void> _handleSubmit() async {
    if (!_formKey.currentState!.validate()) return;

    setState(() => _isLoading = true);

    try {
      // 1. Call Repository Directly (Bypassing global AuthController to avoid triggering AuthScreen listener)
      await ref
          .read(authRepositoryProvider)
          .registerDoctor(
            fullName: _fullNameCtrl.text.trim(),
            email: _emailCtrl.text.trim(),
            password: _passwordCtrl.text.trim(),
            specialty: _selectedSpecialty!,
            licenseNumber: _licenseCtrl.text.trim(),
          );

      if (!mounted) return;

      // 2. Show Success Dialog
      showDialog(
        context: context,
        barrierDismissible: false,
        builder: (ctx) => AlertDialog(
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
          ),
          title: const Column(
            children: [
              Icon(
                Icons.verified_user_outlined,
                size: 50,
                color: Color(0xFF4A90E2),
              ),
              SizedBox(height: 10),
              Text("Application Submitted"),
            ],
          ),
          content: const Text(
            "Your profile has been created successfully.\n\n"
            "Our admin team will verify your medical license shortly. "
            "You will receive an email once your account is activated.",
            textAlign: TextAlign.center,
          ),
          actions: [
            TextButton(
              onPressed: () {
                Navigator.pop(ctx);
                context.go('/auth'); // Return to Login
              },
              child: const Text("Back to Login"),
            ),
          ],
        ),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(e.toString().replaceAll("Exception: ", "")),
          backgroundColor: Colors.red,
        ),
      );
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    // Note: We removed the ref.listen() here entirely.

    return Scaffold(
      backgroundColor: Colors.white,
      appBar: AppBar(
        backgroundColor: Colors.white,
        elevation: 0,
        iconTheme: const IconThemeData(color: Colors.black),
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24.0),
          child: Form(
            key: _formKey,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Icon(
                  Icons.local_hospital,
                  size: 60,
                  color: Color(0xFF4A90E2),
                ),
                const SizedBox(height: 16),
                Text(
                  "Join MedIQ Network",
                  textAlign: TextAlign.center,
                  style: GoogleFonts.poppins(
                    fontSize: 26,
                    fontWeight: FontWeight.bold,
                    color: const Color(0xFF2D3436),
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  "Connect with patients and grow your practice.",
                  textAlign: TextAlign.center,
                  style: GoogleFonts.lato(color: Colors.grey[600]),
                ),
                const SizedBox(height: 32),

                _buildTextField(
                  "Full Name",
                  _fullNameCtrl,
                  Icons.person_outline,
                ),
                const SizedBox(height: 16),
                _buildTextField(
                  "Email Address",
                  _emailCtrl,
                  Icons.email_outlined,
                ),
                const SizedBox(height: 16),
                _buildTextField(
                  "Password",
                  _passwordCtrl,
                  Icons.lock_outline,
                  isPassword: true,
                ),
                const SizedBox(height: 16),

                // Specialty Dropdown
                DropdownButtonFormField<String>(
                  value: _selectedSpecialty,
                  decoration: InputDecoration(
                    labelText: "Specialty",
                    prefixIcon: const Icon(Icons.work_outline, size: 20),
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                    enabledBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(12),
                      borderSide: BorderSide(color: Colors.grey[300]!),
                    ),
                  ),
                  items: _specialties.map((String value) {
                    return DropdownMenuItem<String>(
                      value: value,
                      child: Text(value),
                    );
                  }).toList(),
                  onChanged: (newValue) {
                    setState(() {
                      _selectedSpecialty = newValue;
                    });
                  },
                  validator: (value) =>
                      value == null ? "Please select a specialty" : null,
                ),

                const SizedBox(height: 16),
                _buildTextField(
                  "License #",
                  _licenseCtrl,
                  Icons.badge_outlined,
                ),

                const SizedBox(height: 24),

                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: Colors.amber.withOpacity(0.1),
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: Colors.amber.withOpacity(0.5)),
                  ),
                  child: Row(
                    children: [
                      const Icon(
                        Icons.info_outline,
                        color: Colors.amber,
                        size: 20,
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Text(
                          "Your account will require verification before activation.",
                          style: GoogleFonts.lato(
                            fontSize: 12,
                            color: Colors.brown,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 24),

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
      ),
    );
  }

  Widget _buildTextField(
    String label,
    TextEditingController controller,
    IconData icon, {
    bool isPassword = false,
  }) {
    return TextFormField(
      controller: controller,
      obscureText: isPassword,
      decoration: InputDecoration(
        labelText: label,
        prefixIcon: Icon(icon, size: 20),
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: Colors.grey[300]!),
        ),
      ),
      validator: (value) => value == null || value.isEmpty ? "Required" : null,
    );
  }
}
