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
    final theme = Theme.of(context);

    return Scaffold(
      backgroundColor: theme.scaffoldBackgroundColor,
      appBar: AppBar(
        title: Text("My Profile", style: theme.textTheme.titleLarge),
        backgroundColor: theme.appBarTheme.backgroundColor,
        elevation: 0,
        centerTitle: false,
      ),
      body: userAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (err, stack) => Center(child: Text("Error: $err")),
        data: (user) {
          final String firstName = user?.firstName ?? "";
          final String lastName = user?.lastName ?? "";
          final String email = user?.email ?? "";
          final initials = firstName.isNotEmpty
              ? "${firstName[0]}${lastName.isNotEmpty ? lastName[0] : ''}"
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
                        backgroundImage: (user?.imageUrl != null && user!.imageUrl.isNotEmpty)
                            ? NetworkImage(user.imageUrl)
                            : null,
                        child: (user?.imageUrl == null || user!.imageUrl.isEmpty)
                            ? Text(initials,
                                style: const TextStyle(
                                    fontSize: 32,
                                    fontWeight: FontWeight.bold,
                                    color: Colors.white))
                            : null,
                      ),
                      const SizedBox(height: 16),
                      Text("$firstName $lastName",
                          style: theme.textTheme.displayMedium
                              ?.copyWith(fontSize: 22)),
                      Text(email, style: theme.textTheme.bodyMedium),
                    ],
                  ),
                ),
                const SizedBox(height: 32),
                _buildProfileItem(context,
                    icon: Icons.edit_outlined, text: "Edit Profile", onTap: () {
                  if (user != null) context.push('/edit_profile', extra: user);
                }),
                _buildProfileItem(context,
                    icon: Icons.history,
                    text: "Medical History",
                    onTap: () => context.push('/medical_history')),
                _buildProfileItem(context,
                    icon: Icons.star_border,
                    text: "Manage Subscription",
                    iconColor: Colors.amber,
                    onTap: () => context.push('/subscription')),
                _buildProfileItem(context,
                    icon: Icons.settings_outlined,
                    text: "Settings",
                    onTap: () => context.push('/settings')),
                const Divider(height: 32),
                _buildProfileItem(context,
                    icon: Icons.logout,
                    text: "Logout",
                    textColor: Colors.red,
                    iconColor: Colors.red, onTap: () async {
                  await ref.read(authControllerProvider.notifier).logout();
                  if (context.mounted) context.go('/auth');
                }),
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _buildProfileItem(BuildContext context,
      {required IconData icon,
      required String text,
      required VoidCallback onTap,
      Color? textColor,
      Color? iconColor}) {
    final theme = Theme.of(context);
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(
        color: theme.cardTheme.color,
        borderRadius: BorderRadius.circular(12),
        boxShadow: theme.brightness == Brightness.dark
            ? []
            : [
                BoxShadow(
                    color: Colors.grey.withOpacity(0.05),
                    blurRadius: 5,
                    offset: const Offset(0, 2))
              ],
      ),
      child: ListTile(
        leading: Icon(icon, color: iconColor ?? theme.iconTheme.color),
        title: Text(text,
            style: theme.textTheme.bodyLarge
                ?.copyWith(color: textColor, fontWeight: FontWeight.w500)),
        trailing: const Icon(Icons.chevron_right, color: Colors.grey),
        onTap: onTap,
      ),
    );
  }
}
