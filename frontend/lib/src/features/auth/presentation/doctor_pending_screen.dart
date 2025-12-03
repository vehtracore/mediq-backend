import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:google_fonts/google_fonts.dart';
import '../data/auth_repository.dart';
import 'auth_controller.dart';

class DoctorPendingScreen extends ConsumerStatefulWidget {
  const DoctorPendingScreen({super.key});

  @override
  ConsumerState<DoctorPendingScreen> createState() =>
      _DoctorPendingScreenState();
}

class _DoctorPendingScreenState extends ConsumerState<DoctorPendingScreen> {
  bool _isLoading = false;

  Future<void> _checkStatus() async {
    setState(() => _isLoading = true);
    try {
      // 1. Fetch Profile
      final doctor = await ref
          .read(authRepositoryProvider)
          .getMyDoctorProfile();

      if (!mounted) return;

      // 2. Check Verification
      if (doctor.isVerified) {
        // Success: Verified
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text("Account Verified! Accessing Dashboard..."),
            backgroundColor: Colors.green,
          ),
        );
        context.go('/doctor_home');
      } else {
        // Still Pending
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text("Still pending review. Please try again later."),
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text("Error checking status: $e"),
            backgroundColor: Colors.red,
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  Future<void> _handleLogout() async {
    await ref.read(authControllerProvider.notifier).logout();
    if (mounted) context.go('/auth');
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.white,
      body: Padding(
        padding: const EdgeInsets.all(32.0),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            // Icon
            Container(
              padding: const EdgeInsets.all(24),
              decoration: BoxDecoration(
                color: Colors.orange.withOpacity(0.1),
                shape: BoxShape.circle,
              ),
              child: const Icon(
                Icons.hourglass_empty,
                size: 64,
                color: Colors.orange,
              ),
            ),
            const SizedBox(height: 32),

            // Text
            Text(
              "Verification Pending",
              style: GoogleFonts.poppins(
                fontSize: 24,
                fontWeight: FontWeight.bold,
                color: const Color(0xFF2D3436),
              ),
            ),
            const SizedBox(height: 16),
            Text(
              "Your medical license is currently under review by MedIQ Admins. This process typically takes 24-48 hours.",
              textAlign: TextAlign.center,
              style: GoogleFonts.lato(
                fontSize: 16,
                color: Colors.grey[600],
                height: 1.5,
              ),
            ),
            const SizedBox(height: 48),

            // Refresh Button
            SizedBox(
              width: double.infinity,
              height: 50,
              child: ElevatedButton(
                onPressed: _isLoading ? null : _checkStatus,
                style: ElevatedButton.styleFrom(
                  backgroundColor: const Color(0xFF4A90E2),
                  foregroundColor: Colors.white,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(12),
                  ),
                ),
                child: _isLoading
                    ? const CircularProgressIndicator(color: Colors.white)
                    : const Text("Refresh Status"),
              ),
            ),
            const SizedBox(height: 16),

            // Logout
            TextButton(
              onPressed: _handleLogout,
              style: TextButton.styleFrom(foregroundColor: Colors.grey),
              child: const Text("Logout"),
            ),
          ],
        ),
      ),
    );
  }
}
