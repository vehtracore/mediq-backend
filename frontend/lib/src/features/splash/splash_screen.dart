import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:supabase_flutter/supabase_flutter.dart' hide User;

class SplashScreen extends ConsumerStatefulWidget {
  const SplashScreen({super.key});
  @override
  ConsumerState<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends ConsumerState<SplashScreen> {
  @override
  void initState() {
    super.initState();
    _checkFirstLaunch();
  }

  // ---------------------------------------------------------------------------
  // _checkFirstLaunch
  //
  // The GoRouter redirect (app_router.dart) is now the SOLE authority for all
  // role-based navigation.  The only job left for the splash screen is to
  // detect brand-new users (no session at all) and show the Onboarding flow.
  //
  // For authenticated users, we simply wait — the router's resolvedRoleProvider
  // will fire once the role is loaded and trigger an automatic redirect to the
  // correct dashboard with NO risk of a race condition.
  // ---------------------------------------------------------------------------
  Future<void> _checkFirstLaunch() async {
    // Minimum display time so the splash logo is visible.
    await Future.delayed(const Duration(milliseconds: 800));
    if (!mounted) return;

    final session = Supabase.instance.client.auth.currentSession;

    if (session == null) {
      // Genuinely new / logged-out user — show onboarding.
      // The router will also handle this case but we fast-path here to avoid
      // showing the loading spinner longer than necessary.
      context.go('/onboarding');
    }
    // If session != null: do nothing. The GoRouter redirect is already
    // watching resolvedRoleProvider and will push to the correct dashboard
    // as soon as the role resolves.  No competing navigation needed.
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
