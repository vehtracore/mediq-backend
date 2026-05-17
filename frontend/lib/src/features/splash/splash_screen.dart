import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:supabase_flutter/supabase_flutter.dart' hide User;
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
    // Brief pause so the splash animation is visible
    await Future.delayed(const Duration(milliseconds: 800));
    if (!mounted) return;

    try {
      // Supabase.instance.client.auth.currentSession is synchronously available
      // after Supabase.initialize() resolves in main(). No race condition.
      final session = Supabase.instance.client.auth.currentSession;

      if (session == null) {
        // No valid session — go to onboarding for new users
        context.go('/onboarding');
        return;
      }

      // Session exists: fetch the backend user profile to determine role
      try {
        final user = await ref.read(userProvider.future);
        if (!mounted) return;

        if (user?.role == 'doctor') {
          try {
            final doctor =
                await ref.read(authRepositoryProvider).getMyDoctorProfile();
            switch (doctor.status) {
              case 'active':
                context.go('/doctor_home');
              case 'rejected':
                context.go('/doctor_rejected');
              default:
                context.go('/auth');
            }
          } catch (_) {
            context.go('/auth');
          }
        } else if (user?.role == 'admin') {
          context.go('/admin_dashboard');
        } else {
          context.go('/patient_home');
        }
      } catch (_) {
        // Backend unreachable but Supabase session is valid— send to auth to retry
        context.go('/auth');
      }
    } catch (e) {
      if (mounted) context.go('/auth');
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF4A90E2),
      body: Stack(
        children: [
          Center(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const Icon(Icons.health_and_safety, size: 100, color: Colors.white),
                const SizedBox(height: 16),
                // FIX: Removed GoogleFonts. Using standard TextStyle so text appears offline.
                const Text(
                  "MDQ+",
                  style: TextStyle(
                    fontSize: 40,
                    fontWeight: FontWeight.bold,
                    color: Colors.white,
                  ),
                ),
                const SizedBox(height: 40),
                const CircularProgressIndicator(color: Colors.white),
                const SizedBox(height: 50),
                TextButton.icon(
                  onPressed: () async {
                    await Supabase.instance.client.auth.signOut();
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
          // --- BRANDING WATERMARK ---
          Positioned(
            left: 0,
            right: 0,
            bottom: 0,
            child: SafeArea(
              child: Padding(
                padding: const EdgeInsets.only(bottom: 16.0),
                child: Center(
                  child: Text(
                    'Powered by Vehtr',
                    style: TextStyle(
                      color: Colors.grey.shade400,
                      fontSize: 12,
                      letterSpacing: 1.5,
                    ),
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
