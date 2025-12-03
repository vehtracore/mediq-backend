import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:mediq_app/src/core/storage/storage_service.dart';
import 'package:mediq_app/src/features/auth/presentation/user_controller.dart';
import 'package:mediq_app/src/features/auth/data/auth_repository.dart';

class SplashScreen extends ConsumerStatefulWidget {
  const SplashScreen({super.key});
  @override
  ConsumerState<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends ConsumerState<SplashScreen> {
  @override
  void initState() {
    super.initState();
    _checkSession();
  }

  Future<void> _checkSession() async {
    await Future.delayed(const Duration(seconds: 2));
    // Wrap in try-catch to prevent getting stuck
    try {
      final token = await ref.read(storageServiceProvider).getToken();
      if (token != null && token.isNotEmpty) {
        try {
          final user = await ref.read(userProvider.future);
          if (!mounted) return;

          if (user.role == 'doctor') {
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
          } else if (user.role == 'admin') {
            context.go('/admin_dashboard');
          } else {
            context.go('/patient_home');
          }
        } catch (e) {
          // Token invalid (401) -> Go to Auth
          context.go('/auth');
        }
      } else {
        context.go('/onboarding');
      }
    } catch (e) {
      // Storage error -> Go to Auth
      context.go('/auth');
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF4A90E2),
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.health_and_safety, size: 100, color: Colors.white),
            const SizedBox(height: 16),
            Text(
              "MDQ+",
              style: GoogleFonts.poppins(
                fontSize: 40,
                fontWeight: FontWeight.bold,
                color: Colors.white,
              ),
            ),
            const SizedBox(height: 40),
            const CircularProgressIndicator(color: Colors.white),
            const SizedBox(height: 50),
            // --- EMERGENCY RESET BUTTON ---
            TextButton.icon(
              onPressed: () async {
                await ref.read(storageServiceProvider).deleteToken();
                if (context.mounted) context.go('/auth');
              },
              icon: const Icon(Icons.delete_forever, color: Colors.white70),
              label: const Text(
                "Stuck? Clear Data",
                style: TextStyle(color: Colors.white70),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
