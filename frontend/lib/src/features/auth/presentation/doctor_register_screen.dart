import 'dart:io'; // Needed for File (Mobile only)
import 'package:flutter/foundation.dart'; // Needed for kIsWeb check
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';
import 'package:mediq_app/src/features/auth/data/auth_repository.dart';
import 'package:mediq_app/src/features/media/data/media_repository.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:url_launcher/url_launcher.dart';

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
  bool _isPasswordObscured = true;

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
  void initState() {
    super.initState();
    _loadSavedData();
    _fullNameCtrl.addListener(() => _saveData('doc_reg_name', _fullNameCtrl.text));
    _emailCtrl.addListener(() => _saveData('doc_reg_email', _emailCtrl.text));
    _licenseNumberCtrl.addListener(() => _saveData('doc_reg_license', _licenseNumberCtrl.text));
  }

  Future<void> _loadSavedData() async {
    final prefs = await SharedPreferences.getInstance();
    if (mounted) {
      setState(() {
        _fullNameCtrl.text = prefs.getString('doc_reg_name') ?? '';
        _emailCtrl.text = prefs.getString('doc_reg_email') ?? '';
        _licenseNumberCtrl.text = prefs.getString('doc_reg_license') ?? '';
      });
    }
  }

  Future<void> _saveData(String key, String value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(key, value);
  }

  Future<void> _clearSavedData() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('doc_reg_name');
    await prefs.remove('doc_reg_email');
    await prefs.remove('doc_reg_license');
  }

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

      await _clearSavedData();

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
    final theme = Theme.of(context);
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
      backgroundColor: theme.scaffoldBackgroundColor,
      appBar: AppBar(
        title: const Text("Doctor Registration"),
        backgroundColor: theme.scaffoldBackgroundColor,
        elevation: 0,
        foregroundColor: theme.colorScheme.onSurface,
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
                initialValue: _selectedSpecialty,
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
                    color: theme.brightness == Brightness.dark ? Colors.white.withOpacity(0.05) : Colors.grey[100],
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: theme.brightness == Brightness.dark ? Colors.white.withOpacity(0.1) : Colors.grey[300]!),
                    image: licenseProvider != null
                        ? DecorationImage(
                            image: licenseProvider,
                            fit: BoxFit.cover,
                          )
                        : null,
                  ),
                  child: _licenseImage == null
                      ? Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Icon(
                              Icons.cloud_upload_outlined,
                              size: 40,
                              color: theme.colorScheme.onSurfaceVariant,
                            ),
                            const SizedBox(height: 8),
                            Text(
                              "Tap to upload License Image",
                              style: TextStyle(color: theme.colorScheme.onSurfaceVariant),
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
                    color: theme.brightness == Brightness.dark ? Colors.white.withOpacity(0.05) : Colors.grey[100],
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: theme.brightness == Brightness.dark ? Colors.white.withOpacity(0.1) : Colors.grey[300]!),
                    image: indemnityProvider != null
                        ? DecorationImage(
                            image: indemnityProvider,
                            fit: BoxFit.cover,
                          )
                        : null,
                  ),
                  child: _indemnityImage == null
                      ? Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Icon(
                              Icons.cloud_upload_outlined,
                              size: 40,
                              color: theme.colorScheme.onSurfaceVariant,
                            ),
                            const SizedBox(height: 8),
                            Text(
                              "Tap to upload Indemnity Certificate",
                              style: TextStyle(color: theme.colorScheme.onSurfaceVariant),
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
                onTapLink: () => _launchURL("https://mdqplus.com/legal.html#privacy"),
              ),
              _buildLegalCheckbox(
                title: "I agree to the ",
                linkText: "Terms & Conditions",
                value: _agreedToTC,
                onChanged: (v) => setState(() => _agreedToTC = v!),
                onTapLink: () => _launchURL("https://mdqplus.com/legal.html#terms"),
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
      obscureText: isPassword ? _isPasswordObscured : false,
      decoration: InputDecoration(
        labelText: label,
        prefixIcon: Icon(icon),
        suffixIcon: isPassword
            ? IconButton(
                icon: Icon(_isPasswordObscured
                    ? Icons.visibility_off
                    : Icons.visibility),
                onPressed: () {
                  setState(() {
                    _isPasswordObscured = !_isPasswordObscured;
                  });
                },
              )
            : null,
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
      ),
      validator: (v) {
        if (label == "Email") {
          if (v == null || v.isEmpty) return 'Please enter your email';
          final bool emailValid = RegExp(r"^[a-zA-Z0-9.a-zA-Z0-9.!#$%&'*+-/=?^_{|}~]+@[a-zA-Z0-9]+\.[a-zA-Z]+").hasMatch(v ?? '');
          if (!emailValid) return 'Please enter a valid email address';
        } else if (v == null || v.isEmpty) {
          return "Required";
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
    final theme = Theme.of(context);
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        color: theme.colorScheme.primaryContainer.withOpacity(0.3),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: theme.colorScheme.primary.withOpacity(0.2)),
      ),
      child: Row(
        children: [
          Checkbox(value: value, onChanged: onChanged),
          Expanded(
            child: GestureDetector(
              onTap: onTapLink,
              child: RichText(
                text: TextSpan(
                  style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurface),
                  children: [
                    TextSpan(text: title),
                    TextSpan(
                      text: linkText,
                      style: TextStyle(
                        color: theme.colorScheme.primary,
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

  Future<void> _launchURL(String urlString) async {
    try {
      final Uri url = Uri.parse(urlString);
      if (!await launchUrl(url, mode: LaunchMode.externalApplication)) {
        throw Exception('Could not launch $urlString');
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not open link: $e'), backgroundColor: Colors.red),
        );
      }
    }
  }
}