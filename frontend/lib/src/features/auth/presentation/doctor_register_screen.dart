import 'dart:io'; // Needed for File (Mobile only)
import 'package:flutter/foundation.dart'; // Needed for kIsWeb check
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
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
  bool _agreedToPrivacy = false;
  bool _agreedToTC = false;

  final _fullNameCtrl = TextEditingController();
  final _emailCtrl = TextEditingController();
  final _passwordCtrl = TextEditingController();
  final _licenseNumberCtrl = TextEditingController();

  XFile? _licenseImage;
  XFile? _indemnityImage;

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
    _licenseNumberCtrl.dispose();
    super.dispose();
  }

  // --- Image Picker Logic (Web Safe) ---
  Future<void> _pickLicenseImage() async {
    final picker = ImagePicker();
    final XFile? pickedFile = await picker.pickImage(
      source: ImageSource.gallery,
      imageQuality: 90,
      maxWidth: 1920,
      maxHeight: 1920,
    );

    if (pickedFile != null) {
      setState(() {
        _licenseImage = pickedFile; 
      });
    }
  }

  Future<void> _pickIndemnityImage() async {
    final picker = ImagePicker();
    final XFile? pickedFile = await picker.pickImage(
      source: ImageSource.gallery,
      imageQuality: 90,
      maxWidth: 1920,
      maxHeight: 1920,
    );

    if (pickedFile != null) {
      setState(() {
        _indemnityImage = pickedFile; 
      });
    }
  }

  Future<void> _handleSubmit() async {
    if (!_formKey.currentState!.validate()) return;

    if (!_agreedToPrivacy || !_agreedToTC) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text("Please accept the legal terms to apply."),
          backgroundColor: Colors.red,
        ),
      );
      return;
    }

    if (_licenseImage == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text("Please upload your Medical License image"),
          backgroundColor: Colors.red,
        ),
      );
      return;
    }

    if (_indemnityImage == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text("Please upload your Indemnity Certificate"),
          backgroundColor: Colors.red,
        ),
      );
      return;
    }

    setState(() => _isLoading = true);

    try {
      // 1. Register Doctor
      await ref.read(authRepositoryProvider).registerDoctor(
        fullName: _fullNameCtrl.text.trim(),
        email: _emailCtrl.text.trim(),
        password: _passwordCtrl.text.trim(),
        specialty: _selectedSpecialty!,
        licenseNumber: _licenseNumberCtrl.text.trim(),
        mdcnLicense: _licenseImage!,
        indemnityCertificate: _indemnityImage!,
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
    ImageProvider? licenseProvider;
    if (_licenseImage != null) {
      if (kIsWeb) {
        licenseProvider = NetworkImage(_licenseImage!.path);
      } else {
        licenseProvider = FileImage(File(_licenseImage!.path));
      }
    }

    ImageProvider? indemnityProvider;
    if (_indemnityImage != null) {
      if (kIsWeb) {
        indemnityProvider = NetworkImage(_indemnityImage!.path);
      } else {
        indemnityProvider = FileImage(File(_indemnityImage!.path));
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
              _buildTextField(
                "MDCN License Number",
                _licenseNumberCtrl,
                Icons.badge,
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
                    image: licenseProvider != null
                        ? DecorationImage(
                            image: licenseProvider,
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
              const SizedBox(height: 24),
              const Text(
                "Indemnity Certificate",
                style: TextStyle(fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 8),
              GestureDetector(
                onTap: _pickIndemnityImage,
                child: Container(
                  height: 150,
                  width: double.infinity,
                  decoration: BoxDecoration(
                    color: Colors.grey[100],
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: Colors.grey[300]!),
                    image: indemnityProvider != null
                        ? DecorationImage(
                            image: indemnityProvider,
                            fit: BoxFit.cover,
                          )
                        : null,
                  ),
                  child: _indemnityImage == null
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
                              "Tap to upload Indemnity Certificate",
                              style: TextStyle(color: Colors.grey),
                            ),
                          ],
                        )
                      : null,
                ),
              ),
              const SizedBox(height: 24),
              _buildLegalCheckbox(
                title: "I agree to the ",
                linkText: "Privacy Policy",
                value: _agreedToPrivacy,
                onChanged: (v) => setState(() => _agreedToPrivacy = v!),
                onTapLink: () => _showLegalSheet(
                  "MDQ+ Privacy Policy & User Agreement",
                  _buildPrivacyPolicy(),
                ),
              ),
              _buildLegalCheckbox(
                title: "I agree to the ",
                linkText: "Terms & Conditions",
                value: _agreedToTC,
                onChanged: (v) => setState(() => _agreedToTC = v!),
                onTapLink: () => _showLegalSheet(
                  "MDQ+ Provider Terms and Conditions",
                  _buildTermsAndConditions(),
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
      validator: (v) {
        if (v == null || v.isEmpty) return "Required";
        
        // 🔒 STRICT VALIDATION
        if (label == "Email") {
          final emailRegex = RegExp(r"^[a-zA-Z0-9.]+@[a-zA-Z0-9]+\.[a-zA-Z]+");
          if (!emailRegex.hasMatch(v)) return "Invalid Email";
        }
        
        if (isPassword && v.length < 6) return "Min 6 chars";
        
        return null;
      },
    );
  }

  Widget _buildLegalCheckbox({
    required String title,
    required String linkText,
    required bool value,
    required ValueChanged<bool?> onChanged,
    required VoidCallback onTapLink,
  }) {
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        color: Colors.blue.withOpacity(0.05),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: Colors.blue.withOpacity(0.2)),
      ),
      child: Row(
        children: [
          Checkbox(value: value, onChanged: onChanged),
          Expanded(
            child: GestureDetector(
              onTap: onTapLink,
              child: RichText(
                text: TextSpan(
                  style: Theme.of(context).textTheme.bodySmall,
                  children: [
                    TextSpan(text: title),
                    TextSpan(
                      text: linkText,
                      style: const TextStyle(
                        color: Colors.blue,
                        fontWeight: FontWeight.bold,
                        decoration: TextDecoration.underline,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  void _showLegalSheet(String title, Widget contentWidget) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent, // Makes the top curves look good
      builder: (ctx) => DraggableScrollableSheet(
        initialChildSize: 0.9, // Opens to 90% of screen height
        minChildSize: 0.5,
        maxChildSize: 0.95,
        builder: (_, scrollController) => Container(
          decoration: BoxDecoration(
            color: Theme.of(context).scaffoldBackgroundColor,
            borderRadius: const BorderRadius.vertical(top: Radius.circular(20)),
          ),
          padding: const EdgeInsets.all(24.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Header
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Expanded(
                    child: Text(
                      title, 
                      style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.bold)
                    ),
                  ),
                  IconButton(
                    icon: const Icon(Icons.close),
                    onPressed: () => Navigator.pop(ctx),
                  )
                ],
              ),
              const Divider(),
              const SizedBox(height: 16),
              // Scrollable Text Content
              Expanded(
                child: SingleChildScrollView(
                  controller: scrollController,
                  child: contentWidget,
                ),
              ),
              const SizedBox(height: 16),
              // Footer Button
              SizedBox(
                width: double.infinity,
                height: 50,
                child: ElevatedButton(
                  onPressed: () => Navigator.pop(ctx),
                  child: const Text("I Understand"),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildPrivacyPolicy() {
    return RichText(
      text: TextSpan(
        style: Theme.of(context).textTheme.bodyMedium?.copyWith(height: 1.5),
        children: const [
          TextSpan(text: "Introduction\n", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
          TextSpan(text: "Welcome to MDQ+. This platform is owned and operated by Vehtr Technology Limited. We are committed to protecting your personal and medical information. This policy outlines how we collect, process, and protect your data.\n\n"),
          TextSpan(text: "Nature of Service (The Technology Intermediary)\n", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
          TextSpan(text: "MDQ+ is a technology infrastructure provider. We provide the digital \"pipe\" that connects you with independent, licensed medical practitioners.\n"),
          TextSpan(text: "• Independent Providers: ", style: TextStyle(fontWeight: FontWeight.bold)),
          TextSpan(text: "This policy does not apply to the independent clinical practices of the doctors on the platform.\n"),
          TextSpan(text: "• Not a Medical Provider: ", style: TextStyle(fontWeight: FontWeight.bold)),
          TextSpan(text: "Vehtr Technology Limited is a technology firm, not a healthcare facility, and does not employ the practitioners.\n\n"),
          TextSpan(text: "Information We Collect\n", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
          TextSpan(text: "• Personal Data: ", style: TextStyle(fontWeight: FontWeight.bold)),
          TextSpan(text: "Name, gender, date of birth, and contact details.\n"),
          TextSpan(text: "• Medical Data: ", style: TextStyle(fontWeight: FontWeight.bold)),
          TextSpan(text: "Symptom descriptions, urinalysis photos, and consultation history.\n"),
          TextSpan(text: "• Technical Data: ", style: TextStyle(fontWeight: FontWeight.bold)),
          TextSpan(text: "IP address, device type, and location data to facilitate local emergency connections.\n"),
          TextSpan(text: "• Professional Data (for Doctors): ", style: TextStyle(fontWeight: FontWeight.bold)),
          TextSpan(text: "MDCN registration numbers and practicing licenses.\n\n"),
          TextSpan(text: "AI & Machine Learning Disclaimer\n", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
          TextSpan(text: "MDQ+ utilizes proprietary ML-inference and Gemini Pro API to provide symptom summaries.\n"),
          TextSpan(text: "• Non-Diagnostic: ", style: TextStyle(fontWeight: FontWeight.bold)),
          TextSpan(text: "All AI-generated outputs are \"Clinical Decision Support\" tools for informational purposes only.\n"),
          TextSpan(text: "• Human-in-the-Loop: ", style: TextStyle(fontWeight: FontWeight.bold)),
          TextSpan(text: "AI results do not constitute a final medical diagnosis or prescription and must be verified by a licensed human doctor.\n\n"),
          TextSpan(text: "How We Use Your Data\n", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
          TextSpan(text: "• Consultations: ", style: TextStyle(fontWeight: FontWeight.bold)),
          TextSpan(text: "To facilitate encrypted video (Agora RTC) and chat sessions.\n"),
          TextSpan(text: "• Payments: ", style: TextStyle(fontWeight: FontWeight.bold)),
          TextSpan(text: "To process transactions through our integrated partners, Paystack and OPay.\n"),
          TextSpan(text: "• Safety: ", style: TextStyle(fontWeight: FontWeight.bold)),
          TextSpan(text: "To provide the \"Emergency\" quick-action feature based on your current location.\n\n"),
          TextSpan(text: "Data Security & Sovereignty\n", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
          TextSpan(text: "• Hardware-Level Siloing: ", style: TextStyle(fontWeight: FontWeight.bold)),
          TextSpan(text: "We utilize Supabase Row Level Security (RLS) to ensure your data is only accessible to you and the doctor you are actively consulting.\n"),
          TextSpan(text: "• Encryption: ", style: TextStyle(fontWeight: FontWeight.bold)),
          TextSpan(text: "All video and chat data is encrypted during transmission.\n"),
          TextSpan(text: "• Storage: ", style: TextStyle(fontWeight: FontWeight.bold)),
          TextSpan(text: "Data is handled in compliance with the Nigeria Data Protection Act (NDPA).\n\n"),
          TextSpan(text: "Your Rights & Age Restrictions\n", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
          TextSpan(text: "• Age Limit: ", style: TextStyle(fontWeight: FontWeight.bold)),
          TextSpan(text: "You must be 18 years or older to create an account.\n"),
          TextSpan(text: "• Access & Withdrawal: ", style: TextStyle(fontWeight: FontWeight.bold)),
          TextSpan(text: "You have the right to request a copy of your data or delete your account at any time.\n\n"),
          TextSpan(text: "Contact Us\n", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
          TextSpan(text: "For questions, please email: Mdqplus.info@gmail.com.\n\nLast Updated: April 4, 2026\nBy clicking \"Agree\" or using the MDQ+ app, you consent to the collection and use of your information as described in this policy."),
        ],
      ),
    );
  }

  Widget _buildTermsAndConditions() {
    return RichText(
      text: TextSpan(
        style: Theme.of(context).textTheme.bodyMedium?.copyWith(height: 1.5),
        children: const [
          TextSpan(text: "Effective Date: March 14, 2026\n\n", style: TextStyle(fontStyle: FontStyle.italic)),
          TextSpan(text: "Nature of the Platform\n", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
          TextSpan(text: "• MDQ+ is a digital health platform owned and operated by Vehtr Technology Limited.\n"),
          TextSpan(text: "• The platform functions strictly as a SaaS marketplace. Vehtr Technology Limited does not provide medical services; all clinical services are rendered by you as an independent third-party professional.\n\n"),
          TextSpan(text: "AI Symptom Checker & ML Inference\n", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
          TextSpan(text: "• The AI Symptom Checker is an informational tool utilizing proprietary ML-inference. AI-generated summaries are \"Clinical Decision Support\" only and require your independent verification and clinical judgment.\n\n"),
          TextSpan(text: "Provider Service Agreement & Indemnity\n", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
          TextSpan(text: "• The Indemnity Clause: ", style: TextStyle(fontWeight: FontWeight.bold)),
          TextSpan(text: "I agree to indemnify and hold harmless Vehtr Technology Limited from any claims, damages, or malpractice lawsuits arising from my clinical decisions, prescriptions, or advice given on the MDQ+ platform.\n"),
          TextSpan(text: "• Insurance Requirement: ", style: TextStyle(fontWeight: FontWeight.bold)),
          TextSpan(text: "I certify that I hold a valid Professional Indemnity (PI) Insurance policy and a current MDCN Annual Practicing License.\n"),
          TextSpan(text: "• Infrastructure Acknowledgment: ", style: TextStyle(fontWeight: FontWeight.bold)),
          TextSpan(text: "I acknowledge that MDQ+ is a technology provider. I am responsible for ensuring the reliability of my own device and internet connection during consultations.\n\n"),
          TextSpan(text: "By clicking \"Agree\", you acknowledge that you have read, understood, and agree to be bound by these Terms and Conditions."),
        ],
      ),
    );
  }
}