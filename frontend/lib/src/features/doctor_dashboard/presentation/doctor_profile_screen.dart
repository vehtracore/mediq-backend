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
    final theme = Theme.of(context);

    return Scaffold(
      backgroundColor: theme.scaffoldBackgroundColor, // ✅ Dynamic Background
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
                    doctor.imageUrl.isNotEmpty &&
                            doctor.imageUrl.startsWith('http')
                        ? CircleAvatar(
                            radius: 50,
                            backgroundImage: NetworkImage(doctor.imageUrl),
                          )
                        : const CircleAvatar(
                            radius: 50,
                            child: Icon(Icons.person),
                          ),
                    const SizedBox(height: 16),
                    Text(
                      doctor.fullName,
                      style: theme.textTheme.headlineSmall
                          ?.copyWith(fontWeight: FontWeight.bold), // ✅ Dynamic
                    ),
                    Text(
                      doctor.specialty,
                      style: theme.textTheme.bodyMedium
                          ?.copyWith(color: Colors.grey), // ✅ Dynamic
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 32),
              _buildOption(context, Icons.edit_outlined, "Edit Public Profile",
                  () => context.push('/doctor_edit_profile', extra: doctor)),
              const SizedBox(height: 12),
              _buildOption(
                  context,
                  Icons.calendar_month_outlined,
                  "Manage Availability",
                  () => context.push('/doctor_availability')),
              const SizedBox(height: 12),
              _buildOption(context, Icons.attach_money, "Payout Settings",
                  () => context.push('/payout_settings')),
              const SizedBox(height: 12),
              _buildOption(context, Icons.settings_outlined, "App Settings",
                  () => context.push('/settings')),
              const SizedBox(height: 40),
              _buildOption(context, Icons.logout, "Logout", () async {
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
    BuildContext context,
    IconData icon,
    String title,
    VoidCallback onTap, {
    bool isDestructive = false,
  }) {
    final theme = Theme.of(context);

    return Container(
      decoration: BoxDecoration(
        color: theme.cardTheme.color, // ✅ Dynamic Background
        borderRadius: BorderRadius.circular(12),
        boxShadow: theme.brightness == Brightness.dark
            ? []
            : [
                BoxShadow(
                  color: Colors.grey.withValues(alpha: 0.05),
                  blurRadius: 5,
                )
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
            color: isDestructive
                ? Colors.red
                : theme.textTheme.bodyLarge?.color, // ✅ Dynamic Text
          ),
        ),
        trailing: const Icon(Icons.chevron_right, color: Colors.grey),
        onTap: onTap,
      ),
    );
  }
}
