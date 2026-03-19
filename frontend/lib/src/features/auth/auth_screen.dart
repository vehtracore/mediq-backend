import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';
import 'package:url_launcher/url_launcher.dart'; // ✅ Added for Google Auth
import 'presentation/auth_controller.dart';
import 'presentation/user_controller.dart';
import 'data/auth_repository.dart';
import 'package:mediq_app/src/features/doctors/data/doctor_model.dart';

class AuthScreen extends ConsumerStatefulWidget {
  const AuthScreen({super.key});

  @override
  ConsumerState<AuthScreen> createState() => _AuthScreenState();
}

class _AuthScreenState extends ConsumerState<AuthScreen> {
  bool _isLogin = true;
  final _firstNameController = TextEditingController();
  final _lastNameController = TextEditingController();
  final _locationController = TextEditingController();
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  DateTime? _selectedDate;
  bool _agreedToPrivacy = false;
  bool _agreedToTC = false;
  bool _obscurePassword = true;  // ✅ State for password visibility
  final _formKey = GlobalKey<FormState>();

  @override
  void dispose() {
    _firstNameController.dispose();
    _lastNameController.dispose();
    _locationController.dispose();
    _emailController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  Future<void> _pickDate() async {
    final now = DateTime.now();
    final eighteenYearsAgo = DateTime(now.year - 18, now.month, now.day);
    final picked = await showDatePicker(
      context: context,
      initialDate: DateTime(2000),
      firstDate: DateTime(1900),
      lastDate: eighteenYearsAgo,
      helpText: 'You must be 18 or older to create an account.',
    );
    if (picked != null) setState(() => _selectedDate = picked);
  }

  Future<void> _navigateAfterAuth() async {
    if (!mounted) return;
    
    try {
      // FIX: Call repository directly to avoid Potential Riverpod Refresh hang
      final authRepo = ref.read(authRepositoryProvider);
      final user = await authRepo.getUserProfile();
      
      // Update the provider manually to keep state in sync
      if (user != null) {
         ref.invalidate(userProvider);
      }
      
      if (!mounted) return;

      // Redirect based on role
      if (user?.role == 'admin') {
        context.go('/admin_dashboard');
      } else if (user?.role == 'doctor') {
        try {
          final doctor = await ref.read(authRepositoryProvider).getMyDoctorProfile();
          if (!mounted) return;
          if (doctor.isVerified) {
            context.go('/doctor_home');
          } else {
            context.go('/doctor_pending');
          }
        } catch (e) {
          if (mounted) context.go('/doctor_pending');
        }
      } else {
        context.go('/patient_home');
      }
    } catch (e) {
      // Fallback if user fetch fails but login succeeded
      if (mounted) context.go('/patient_home');
    }
  }

  Future<void> _handleSubmit() async {
    if (!_formKey.currentState!.validate()) return;
    if (!_isLogin && (_selectedDate == null || !_agreedToPrivacy || !_agreedToTC)) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text("Please complete all fields and accept the legal terms."),
        ),
      );
      return;
    }

    final controller = ref.read(authControllerProvider.notifier);
    
    // ✅ FIX: Use Positional Arguments to match AuthController
    if (_isLogin) {
      await controller.login(
        _emailController.text.trim(),
        _passwordController.text.trim(),
      );
    } else {
      // ✅ FIX: Pass exactly 4 arguments as required by the Controller
      await controller.signUp(
        _emailController.text.trim(),
        _passwordController.text.trim(),
        _firstNameController.text.trim(),
        _lastNameController.text.trim(),
        _selectedDate!, // ✅ Pass DOB
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final authState = ref.watch(authControllerProvider);
    final theme = Theme.of(context);

    ref.listen<AsyncValue<void>>(authControllerProvider,
        (previous, next) {
      if (next.hasError) {
        String errorMsg = next.error.toString();
        // The Repository now throws clean Exceptions like "Exception: Email already registered"
        // We just need to remove the "Exception: " prefix
        if (errorMsg.startsWith("Exception: ")) {
          errorMsg = errorMsg.replaceFirst("Exception: ", "");
        }

        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(errorMsg),
            backgroundColor: Colors.red,
          ),
        );
        return;
      }
      
      // ✅ FIX: Only navigate when transitioning FROM loading state (after actual login/signup)
      final wasLoading = previous?.isLoading ?? false;
      if (wasLoading && !next.isLoading && !next.hasError) {
        // Navigate immediately - call helper method
        _navigateAfterAuth();
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
                const Icon(
                  Icons.health_and_safety,
                  size: 64,
                  color: Color(0xFF4A90E2),
                ),
                const SizedBox(height: 24),
                Text(
                  _isLogin ? "Welcome Back" : "Create Profile",
                  style: theme.textTheme.headlineMedium,
                ),
                const SizedBox(height: 32),
                if (!_isLogin) ...[
                  Row(
                    children: [
                      Expanded(
                        child: TextFormField(
                          controller: _firstNameController,
                          decoration:
                              const InputDecoration(labelText: "First Name"),
                          validator: (v) => v!.isEmpty ? "Required" : null,
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: TextFormField(
                          controller: _lastNameController,
                          decoration:
                              const InputDecoration(labelText: "Last Name"),
                          validator: (v) => v!.isEmpty ? "Required" : null,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 16),
                  Row(
                    children: [
                      Expanded(
                        child: InkWell(
                          onTap: _pickDate,
                          child: InputDecorator(
                            decoration: const InputDecoration(labelText: "DOB"),
                            child: Text(
                              _selectedDate == null
                                  ? "Select"
                                  : DateFormat('yyyy-MM-dd').format(_selectedDate!),
                            ),
                          ),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: TextFormField(
                          controller: _locationController,
                          decoration: const InputDecoration(labelText: "City"),
                          // Note: Location is collected but not sent to signup yet
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 16),
                ],
                  TextFormField(
                    controller: _emailController,
                    decoration: const InputDecoration(labelText: "Email"),
                    validator: (v) {
                       // ✅ Email Regex
                       final emailRegex = RegExp(r"^[a-zA-Z0-9.]+@[a-zA-Z0-9]+\.[a-zA-Z]+");
                       if (v == null || v.isEmpty || !emailRegex.hasMatch(v)) {
                         return "Enter a valid email (e.g., name@domain.com)";
                       }
                       return null;
                    },
                  ),
                const SizedBox(height: 16),
                  TextFormField(
                    controller: _passwordController,
                    obscureText: _obscurePassword, // ✅ Toggles
                    decoration: InputDecoration(
                      labelText: "Password",
                      suffixIcon: IconButton( // ✅ Eye Button
                        icon: Icon(
                          _obscurePassword ? Icons.visibility_off : Icons.visibility,
                        ),
                        onPressed: () {
                          setState(() {
                            _obscurePassword = !_obscurePassword;
                          });
                        },
                      ),
                    ),
                    validator: (v) => (v != null && v.length >= 6) ? null : "Min 6 chars",
                  ),
                if (!_isLogin) ...[
                  const SizedBox(height: 16),
                  _buildLegalCheckbox(
                    title: "I agree to the ",
                    linkText: "Privacy Policy",
                    value: _agreedToPrivacy,
                    onChanged: (v) => setState(() => _agreedToPrivacy = v!),
                    onTapLink: () => _showLegalSheet(
                      "Privacy Policy",
                      "MDQ+ Privacy Policy\n\nYour data is encrypted and securely stored. We comply with medical data protection standards. Your data will not be sold to third parties.",
                    ),
                  ),
                  _buildLegalCheckbox(
                    title: "I agree to the ",
                    linkText: "Terms & Conditions",
                    value: _agreedToTC,
                    onChanged: (v) => setState(() => _agreedToTC = v!),
                    onTapLink: () => _showLegalSheet(
                      "Telemedicine Informed Consent",
                      "Telemedicine Informed Consent\n\n1. I understand MDQ+ uses AI for preliminary analysis, which is NOT a substitute for professional medical advice.\n2. I understand that MDQ+ is NOT for medical emergencies. In an emergency, I will contact local emergency services immediately.\n3. I consent to telemedicine consultations with licensed practitioners.",
                    ),
                  ),
                ],
                const SizedBox(height: 32),
                SizedBox(
                  width: double.infinity,
                  height: 50,
                  child: ElevatedButton(
                    onPressed: authState.isLoading ? null : _handleSubmit,
                    child: authState.isLoading
                        ? const CircularProgressIndicator()
                        : Text(_isLogin ? "Login" : "Sign Up"),
                  ),
                ),
                const SizedBox(height: 16),
                
                // --- 🔴 Google Sign In Button ---
                if (_isLogin) ...[
                  SizedBox(
                    width: double.infinity,
                    height: 50,
                    child: OutlinedButton.icon(
                      icon: const Text(
                        "G", 
                        style: TextStyle(
                          fontSize: 24, 
                          fontWeight: FontWeight.bold,
                          color: Colors.red, // Google Brand Color
                        ),
                      ),
                      label: const Text(
                        "Sign in with Google",
                        style: TextStyle(
                          fontSize: 16,
                          color: Colors.black87,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                      style: OutlinedButton.styleFrom(
                        backgroundColor: Colors.white,
                        side: const BorderSide(color: Colors.grey),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(30),
                        ),
                      ),
                      onPressed: () async {
                        // 1. Define the backend URL
                        final url = Uri.parse("https://mediq-backend-m3ik.onrender.com/auth/google/login");
                        
                        // 2. Launch in the same tab ('_self') for web flow
                        if (await canLaunchUrl(url)) {
                          await launchUrl(
                            url, 
                            webOnlyWindowName: '_self', // Keeps in same tab
                          );
                        } else {
                          ScaffoldMessenger.of(context).showSnackBar(
                            const SnackBar(content: Text("Could not launch Google Login")),
                          );
                        }
                      },
                    ),
                  ),
                  const SizedBox(height: 16),
                ],
                // --------------------------------
                TextButton(
                  onPressed: () => setState(() => _isLogin = !_isLogin),
                  child: Text(_isLogin ? "Create an account" : "Have an account? Login"),
                ),
                const Divider(),
                TextButton(
                  onPressed: () => context.push('/doctor_register'),
                  child: const Text("Are you a Doctor? Apply here"),
                ),
              ],
            ),
          ),
        ),
      ),
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

  void _showLegalSheet(String title, String content) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (ctx) => Padding(
        padding: const EdgeInsets.all(24.0).copyWith(
          bottom: MediaQuery.of(ctx).padding.bottom + 24,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.bold)),
            const SizedBox(height: 16),
            Text(content, style: Theme.of(context).textTheme.bodyMedium),
            const SizedBox(height: 24),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: () => Navigator.pop(ctx),
                child: const Text("I Understand"),
              ),
            ),
          ],
        ),
      ),
    );
  }
}