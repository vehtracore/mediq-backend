import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';
import 'presentation/auth_controller.dart';
import 'presentation/user_controller.dart';
import 'data/auth_repository.dart'; // Needed for repo access

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
  bool _agreedToTerms = false;
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
    final picked = await showDatePicker(
      context: context,
      initialDate: DateTime(2000),
      firstDate: DateTime(1900),
      lastDate: now,
    );
    if (picked != null) setState(() => _selectedDate = picked);
  }

  Future<void> _handleSubmit() async {
    if (!_formKey.currentState!.validate()) return;
    if (!_isLogin && (_selectedDate == null || !_agreedToTerms)) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text("Please complete fields and accept terms."),
        ),
      );
      return;
    }

    final controller = ref.read(authControllerProvider.notifier);
    if (_isLogin) {
      await controller.login(
        email: _emailController.text.trim(),
        password: _passwordController.text.trim(),
      );
    } else {
      await controller.signUp(
        firstName: _firstNameController.text.trim(),
        lastName: _lastNameController.text.trim(),
        location: _locationController.text.trim(),
        dob: _selectedDate!,
        email: _emailController.text.trim(),
        password: _passwordController.text.trim(),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final authState = ref.watch(authControllerProvider);
    final theme = Theme.of(context);

    ref.listen<AsyncValue<void>>(authControllerProvider, (
      previous,
      next,
    ) async {
      if (next.hasError)
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(next.error.toString()),
            backgroundColor: Colors.red,
          ),
        );
      if (!next.isLoading && !next.hasError) {
        try {
          final user = await ref.refresh(userProvider.future);
          if (!mounted) return;

          if (user.role == 'admin') {
            context.go('/admin_dashboard');
          } else if (user.role == 'doctor') {
            try {
              final doctor = await ref
                  .read(authRepositoryProvider)
                  .getMyDoctorProfile();
              if (doctor.isVerified)
                context.go('/doctor_home');
              else
                context.go('/doctor_pending');
            } catch (e) {
              context.go('/doctor_pending');
            }
          } else {
            context.go('/patient_home');
          }
        } catch (e) {
          context.go('/patient_home');
        }
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
                          decoration: const InputDecoration(
                            labelText: "First Name",
                          ),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: TextFormField(
                          controller: _lastNameController,
                          decoration: const InputDecoration(
                            labelText: "Last Name",
                          ),
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
                                  : DateFormat(
                                      'yyyy-MM-dd',
                                    ).format(_selectedDate!),
                            ),
                          ),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: TextFormField(
                          controller: _locationController,
                          decoration: const InputDecoration(labelText: "City"),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 16),
                ],

                TextFormField(
                  controller: _emailController,
                  decoration: const InputDecoration(labelText: "Email"),
                ),
                const SizedBox(height: 16),
                TextFormField(
                  controller: _passwordController,
                  obscureText: true,
                  decoration: const InputDecoration(labelText: "Password"),
                ),

                if (!_isLogin) ...[
                  const SizedBox(height: 24),
                  // --- RESTORED FULL TEXT ---
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: Colors.blue.withOpacity(0.05),
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: Colors.blue.withOpacity(0.2)),
                    ),
                    child: Row(
                      children: [
                        Checkbox(
                          value: _agreedToTerms,
                          onChanged: (v) => setState(() => _agreedToTerms = v!),
                        ),
                        Expanded(
                          child: Text(
                            "I agree to the Terms of Service and MDQ+ Safety Disclaimer.",
                            style: theme.textTheme.bodySmall,
                          ),
                        ),
                      ],
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

                TextButton(
                  onPressed: () => setState(() => _isLogin = !_isLogin),
                  child: Text(_isLogin ? "Sign Up" : "Login"),
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
}
