import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'package:url_launcher/url_launcher.dart';
import 'presentation/auth_controller.dart';
import 'presentation/user_controller.dart';
import 'data/auth_repository.dart';

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
      if (user == null) {
        context.go('/auth');
      } else if (user.role == 'admin') {
        context.go('/admin_dashboard');
      } else if (user.role == 'doctor') {
        try {
          final doctor = await ref.read(authRepositoryProvider).getMyDoctorProfile();
          if (!mounted) return;
          if (doctor.isVerified) {
            context.go('/doctor_home');
          } else {
            context.go('/');
          }
        } catch (e) {
          if (mounted) context.go('/');
        }
      } else if (user.role == 'patient') {
        context.go('/patient_home');
      } else {
        context.go('/auth');
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('We could not load your profile. Please try again.'),
            backgroundColor: Colors.red,
          ),
        );
        context.go('/auth');
      }
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

  void _showForgotPasswordDialog() {
    final emailController = TextEditingController(text: _emailController.text);
    showDialog(
      context: context,
      builder: (ctx) {
        return AlertDialog(
          title: const Text("Reset Password"),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text("Enter your email address to receive a password reset link."),
              const SizedBox(height: 16),
              TextField(
                controller: emailController,
                decoration: const InputDecoration(
                  labelText: "Email",
                  border: OutlineInputBorder(),
                ),
                keyboardType: TextInputType.emailAddress,
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text("Cancel"),
            ),
            ElevatedButton(
              onPressed: () async {
                final email = emailController.text.trim();
                if (email.isEmpty) return;
                
                try {
                  await Supabase.instance.client.auth.resetPasswordForEmail(
                    email, 
                    redirectTo: 'io.supabase.mediqapp://login-callback',
                  );
                  if (ctx.mounted) {
                    Navigator.pop(ctx);
                  }
                  if (mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text("Check your email for the reset link")),
                    );
                  }
                } catch (e) {
                  if (ctx.mounted) {
                    ScaffoldMessenger.of(ctx).showSnackBar(
                      SnackBar(content: Text("Error: $e")),
                    );
                  }
                }
              },
              child: const Text("Send Link"),
            ),
          ],
        );
      },
    );
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
                      if (v == null || v.isEmpty) return 'Please enter your email';
                      final bool emailValid = RegExp(r"^[a-zA-Z0-9.a-zA-Z0-9.!#$%&'*+-/=?^_{|}~]+@[a-zA-Z0-9]+\.[a-zA-Z]+").hasMatch(v ?? '');
                      if (!emailValid) return 'Please enter a valid email address';
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
                    validator: (value) {
                      if (value == null || value.isEmpty) {
                        return 'Please enter your password';
                      }
                      if (!_isLogin) {
                        if (value.length < 6) return 'Password must be at least 6 characters';
                        if (!RegExp(r'[0-9]').hasMatch(value)) return 'Password must contain at least one number';
                        if (!RegExp(r'[!@#$%^&*(),.?":{}|<>]').hasMatch(value)) return 'Password must contain a special character';
                      }
                      return null;
                    },
                  ),
                if (_isLogin)
                  Align(
                    alignment: Alignment.centerRight,
                    child: TextButton(
                      onPressed: _showForgotPasswordDialog,
                      child: const Text("Forgot Password?"),
                    ),
                  ),
                if (!_isLogin) ...[
                  const SizedBox(height: 16),
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
