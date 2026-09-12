import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart' hide User;

import '../auth/data/auth_state_provider.dart';
import '../auth/presentation/profile_recovery_view.dart';
import '../auth/presentation/user_controller.dart';

class SplashScreen extends ConsumerWidget {
  const SplashScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(supabaseAuthProvider);
    final session = Supabase.instance.client.auth.currentSession ??
        auth.valueOrNull?.session;
    final profile = ref.watch(userProvider);

    if (session != null && profile.hasError) {
      return Scaffold(
        body: AuthenticatedProfileRecoveryView(error: profile.error),
      );
    }

    return Scaffold(
      backgroundColor: const Color(0xFF4A90E2),
      body: Stack(
        children: [
          Center(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const Icon(Icons.health_and_safety,
                    size: 100, color: Colors.white),
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
                if (session != null)
                  const Padding(
                    padding: EdgeInsets.symmetric(horizontal: 32),
                    child: Text(
                      'Restoring your secure session…',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: Colors.white),
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
