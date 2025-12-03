import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:mediq_app/src/features/auth/data/auth_repository.dart';
import 'package:mediq_app/src/features/auth/presentation/auth_controller.dart';

final myDoctorProfileProvider = FutureProvider.autoDispose((ref) async {
  return await ref.watch(authRepositoryProvider).getMyDoctorProfile();
});

class DoctorProfileScreen extends ConsumerWidget {
  const DoctorProfileScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final doctorAsync = ref.watch(myDoctorProfileProvider);

    return Scaffold(
      backgroundColor: const Color(0xFFF9FAFB),
      body: doctorAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text("Error: $e")),
        data: (doctor) {
          return ListView(
            padding: const EdgeInsets.all(24),
            children: [
              Center(
                child: Column(
                  children: [
                    CircleAvatar(
                      radius: 50,
                      backgroundImage: NetworkImage(doctor.imageUrl),
                      onBackgroundImageError: (_, __) =>
                          const Icon(Icons.person),
                    ),
                    const SizedBox(height: 16),
                    Text(
                      doctor.fullName,
                      style: const TextStyle(
                        fontSize: 22,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    Text(
                      doctor.specialty,
                      style: TextStyle(color: Colors.grey[600]),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 32),

              // --- WIRED BUTTONS ---
              _buildOption(
                Icons.edit_outlined,
                "Edit Public Profile",
                () => context.push('/doctor_edit_profile', extra: doctor),
              ),
              const SizedBox(height: 12),
              _buildOption(
                Icons.calendar_month_outlined,
                "Manage Availability",
                () => context.push('/doctor_availability'),
              ),
              const SizedBox(height: 12),
              _buildOption(Icons.attach_money, "Payout Settings", () {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(
                    content: Text("Payout Integration Coming Soon"),
                  ),
                );
              }),
              const SizedBox(height: 12),
              _buildOption(
                Icons.settings_outlined,
                "App Settings",
                () => context.push('/settings'),
              ),

              const SizedBox(height: 40),
              _buildOption(Icons.logout, "Logout", () async {
                await ref.read(authControllerProvider.notifier).logout();
                if (context.mounted) context.go('/auth');
              }, isDestructive: true),
            ],
          );
        },
      ),
    );
  }

  Widget _buildOption(
    IconData icon,
    String title,
    VoidCallback onTap, {
    bool isDestructive = false,
  }) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        boxShadow: [
          BoxShadow(
            color: Colors.grey.withOpacity(0.05),
            blurRadius: 5,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      child: ListTile(
        leading: Icon(
          icon,
          color: isDestructive ? Colors.red : const Color(0xFF4A90E2),
        ),
        title: Text(
          title,
          style: TextStyle(
            fontWeight: FontWeight.w600,
            color: isDestructive ? Colors.red : const Color(0xFF2D3436),
          ),
        ),
        trailing: const Icon(Icons.chevron_right, color: Colors.grey),
        onTap: onTap,
      ),
    );
  }
}
