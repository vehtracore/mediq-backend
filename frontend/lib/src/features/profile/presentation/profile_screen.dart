import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:mediq_app/src/features/auth/presentation/auth_controller.dart';
import 'package:mediq_app/src/features/auth/presentation/user_controller.dart';

class ProfileScreen extends ConsumerWidget {
  const ProfileScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final userAsync = ref.watch(userProvider);

    return Scaffold(
      backgroundColor: const Color(0xFFF9FAFB),
      appBar: AppBar(
        title: const Text("My Profile", style: TextStyle(color: Colors.black)),
        backgroundColor: Colors.white,
        elevation: 0,
        centerTitle: false,
      ),
      body: userAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (err, stack) => Center(child: Text("Error: $err")),
        data: (user) {
          final initials = user.firstName.isNotEmpty
              ? "${user.firstName[0]}${user.lastName.isNotEmpty ? user.lastName[0] : ''}"
                    .toUpperCase()
              : "?";

          return SingleChildScrollView(
            padding: const EdgeInsets.all(24.0),
            child: Column(
              children: [
                Center(
                  child: Column(
                    children: [
                      CircleAvatar(
                        radius: 50,
                        backgroundColor: const Color(0xFF4A90E2),
                        child: Text(
                          initials,
                          style: const TextStyle(
                            fontSize: 32,
                            fontWeight: FontWeight.bold,
                            color: Colors.white,
                          ),
                        ),
                      ),
                      const SizedBox(height: 16),
                      Text(
                        "${user.firstName} ${user.lastName}",
                        style: const TextStyle(
                          fontSize: 22,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      Text(
                        user.email,
                        style: TextStyle(color: Colors.grey[600]),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 32),

                _buildProfileItem(
                  icon: Icons.edit_outlined,
                  text: "Edit Profile",
                  onTap: () => context.push('/edit_profile', extra: user),
                ),

                // --- WIRED BUTTONS ---
                _buildProfileItem(
                  icon: Icons.history,
                  text: "Medical History",
                  onTap: () => context.push('/medical_history'),
                ),

                _buildProfileItem(
                  icon: Icons.star_border,
                  text: "Manage Subscription",
                  iconColor: Colors.amber,
                  onTap: () => context.push('/subscription'),
                ),

                _buildProfileItem(
                  icon: Icons.settings_outlined,
                  text: "Settings",
                  onTap: () => context.push('/settings'),
                ),

                const Divider(height: 32),
                _buildProfileItem(
                  icon: Icons.logout,
                  text: "Logout",
                  textColor: Colors.red,
                  iconColor: Colors.red,
                  onTap: () async {
                    await ref.read(authControllerProvider.notifier).logout();
                    if (context.mounted) context.go('/auth');
                  },
                ),
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _buildProfileItem({
    required IconData icon,
    required String text,
    required VoidCallback onTap,
    Color textColor = Colors.black,
    Color iconColor = Colors.grey,
  }) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
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
        leading: Icon(icon, color: iconColor),
        title: Text(
          text,
          style: TextStyle(color: textColor, fontWeight: FontWeight.w500),
        ),
        trailing: const Icon(Icons.chevron_right, color: Colors.grey),
        onTap: onTap,
      ),
    );
  }
}
