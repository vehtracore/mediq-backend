import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:mediq_app/src/features/auth/presentation/auth_controller.dart';
import 'package:mediq_app/src/features/auth/presentation/user_controller.dart';
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
                if (user != null && user.isFamilyAdmin)
                  _buildProfileItem(context,
                      icon: Icons.family_restroom,
                      text: "Manage Family Plan",
                      iconColor: const Color(0xFF4A90E2),
                      onTap: () => context.push('/family_dashboard')),
                _buildProfileItem(context,
                    icon: Icons.settings_outlined,
                    text: "Settings",
                    onTap: () => context.push('/settings')),
                const Divider(height: 32),
                const Align(
                  alignment: Alignment.centerLeft,
                  child: Text(
                    "Support",
                    style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: Colors.grey),
                  ),
                ),
                const SizedBox(height: 12),
                _buildProfileItem(context,
                    icon: Icons.support_agent,
                    text: "Contact Support",
                    onTap: () {
                      _showSupportModal(context, ref);
                    }),
                const Divider(height: 32),
                if (user != null && user.subscriptionTier == 'free') ...[
                  _buildProfileItem(context,
                      icon: Icons.star,
                      text: "Upgrade Subscription",
                      iconColor: Colors.amber,
                      onTap: () => context.push('/subscription')),
                  const SizedBox(height: 12),
                ],
                if (user != null && user.subscriptionTier != 'free') ...[
                  _buildProfileItem(context,
                      icon: Icons.cancel_outlined,
                      text: "Cancel Subscription",
                      textColor: Colors.red,
                      iconColor: Colors.red, onTap: () async {
                    final confirm = await showDialog<bool>(
                      context: context,
                      builder: (context) => AlertDialog(
                        title: const Text("Cancel Subscription"),
                        content: const Text(
                            "Are you sure you want to cancel your subscription? You will retain access to all premium features until your current billing cycle expires."),
                        actions: [
                          TextButton(
                            onPressed: () => Navigator.of(context).pop(false),
                            child: const Text("No"),
                          ),
                          TextButton(
                            onPressed: () => Navigator.of(context).pop(true),
                            child: const Text("Yes", style: TextStyle(color: Colors.red)),
                          ),
                        ],
                      ),
                    );

                    if (confirm == true) {
                      showDialog(
                        context: context,
                        barrierDismissible: false,
                        builder: (_) => const Center(child: CircularProgressIndicator()),
                      );
                      try {
                        await ref.read(authControllerProvider.notifier).cancelSubscription();
                        if (context.mounted) {
                          Navigator.of(context).pop(); // dismiss loading
                          ScaffoldMessenger.of(context).showSnackBar(
                            const SnackBar(content: Text("Subscription cancelled successfully"), backgroundColor: Colors.green),
                          );
                        }
                      } catch (e) {
                        if (context.mounted) {
                          Navigator.of(context).pop(); // dismiss loading
                          ScaffoldMessenger.of(context).showSnackBar(
                            SnackBar(content: Text(e.toString()), backgroundColor: Colors.red),
                          );
                        }
                      }
                    }
                  }),
                  const SizedBox(height: 12),
                ],
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

  void _showSupportModal(BuildContext context, WidgetRef ref) {
    final subjectController = TextEditingController();
    final messageController = TextEditingController();
    bool isLoading = false;

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(16))),
      builder: (context) {
        return StatefulBuilder(
          builder: (context, setState) {
            return Padding(
              padding: EdgeInsets.only(
                bottom: MediaQuery.of(context).viewInsets.bottom,
                left: 24,
                right: 24,
                top: 24,
              ),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text("Contact Support", style: Theme.of(context).textTheme.titleLarge),
                  const SizedBox(height: 16),
                  TextField(
                    controller: subjectController,
                    decoration: const InputDecoration(labelText: "Subject", border: OutlineInputBorder()),
                  ),
                  const SizedBox(height: 16),
                  TextField(
                    controller: messageController,
                    minLines: 3,
                    maxLines: 5,
                    decoration: const InputDecoration(labelText: "Message", border: OutlineInputBorder()),
                  ),
                  const SizedBox(height: 24),
                  ElevatedButton(
                    onPressed: isLoading
                        ? null
                        : () async {
                            final subject = subjectController.text.trim();
                            final message = messageController.text.trim();
                            if (subject.isEmpty || message.isEmpty) return;

                            setState(() => isLoading = true);
                            try {
                              await ref.read(authControllerProvider.notifier).sendSupportMessage(
                                    subject: subject,
                                    message: message,
                                  );
                              if (context.mounted) {
                                Navigator.pop(context);
                                ScaffoldMessenger.of(context).showSnackBar(
                                  const SnackBar(
                                      content: Text("Message sent successfully. We will get back to you soon."),
                                      backgroundColor: Colors.green),
                                );
                              }
                            } catch (e) {
                              if (context.mounted) {
                                ScaffoldMessenger.of(context).showSnackBar(
                                  SnackBar(content: Text(e.toString()), backgroundColor: Colors.red),
                                );
                              }
                            } finally {
                              if (context.mounted) {
                                setState(() => isLoading = false);
                              }
                            }
                          },
                    child: isLoading
                        ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2))
                        : const Text("Send Message"),
                  ),
                  const SizedBox(height: 24),
                ],
              ),
            );
          },
        );
      },
    );
  }
}
