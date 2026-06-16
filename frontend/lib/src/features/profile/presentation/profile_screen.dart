import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:mediq_app/src/features/auth/data/user_model.dart';
import 'package:mediq_app/src/features/auth/presentation/auth_controller.dart';
import 'package:mediq_app/src/features/auth/presentation/user_controller.dart';

class ProfileScreen extends ConsumerStatefulWidget {
  const ProfileScreen({super.key});

  @override
  ConsumerState<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends ConsumerState<ProfileScreen> {
  bool _isLoggingOut = false;

  @override
  Widget build(BuildContext context) {
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
                // ── Main menu ──────────────────────────────────────────────
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
                    onTap: () {
                      if (user == null || user.subscriptionTier == 'free') {
                        context.push('/subscription');
                      } else {
                        // Pass the full User so the modal can differentiate
                        // Premium / Family Host / Family Dependent.
                        _showManageSubscriptionModal(context, ref, user);
                      }
                    }),
                if (user != null && user.subscriptionTier == 'family')
                  _buildProfileItem(context,
                      icon: Icons.family_restroom,
                      text: "Manage Family Plan",
                      iconColor: const Color(0xFF4A90E2),
                      // Admins go to the full dashboard; dependents see their
                      // "You are on the Family Plan" info on the subscription screen.
                      onTap: () => user.isFamilyAdmin
                          ? context.push('/family_dashboard')
                          : context.push('/subscription')),
                _buildProfileItem(context,
                    icon: Icons.settings_outlined,
                    text: "Settings",
                    onTap: () => context.push('/settings')),
                const Divider(height: 32),
                // ── Support section ────────────────────────────────────────
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
                // ── Logout ─────────────────────────────────────────────────
                _buildProfileItem(context,
                    icon: Icons.logout,
                    text: _isLoggingOut ? "Logging out..." : "Logout",
                    textColor: Colors.red,
                    iconColor: Colors.red,
                    isLoading: _isLoggingOut, onTap: () async {
                  setState(() => _isLoggingOut = true);
                  try {
                    await ref.read(authControllerProvider.notifier).logout();
                    if (context.mounted) context.go('/auth');
                  } finally {
                    if (mounted) setState(() => _isLoggingOut = false);
                  }
                }),
              ],
            ),
          );
        },
      ),
    );
  }

  // ── Reusable list item ────────────────────────────────────────────────────

  Widget _buildProfileItem(BuildContext context,
      {required IconData icon,
      required String text,
      required VoidCallback? onTap,
      Color? textColor,
      Color? iconColor,
      bool isLoading = false}) {
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
        leading: isLoading
            ? const SizedBox(
                width: 24,
                height: 24,
                child: CircularProgressIndicator(strokeWidth: 2),
              )
            : Icon(icon, color: iconColor ?? theme.iconTheme.color),
        title: Text(text,
            style: theme.textTheme.bodyLarge
                ?.copyWith(color: textColor, fontWeight: FontWeight.w500)),
        trailing: isLoading
            ? null
            : const Icon(Icons.chevron_right, color: Colors.grey),
        onTap: isLoading ? null : onTap,
      ),
    );
  }

  // ── Manage Subscription modal ─────────────────────────────────────────────
  //
  // Three states, derived from subscriptionTier + isFamilyAdmin:
  //
  //  State A — Premium          tier == 'premium'
  //            Title : "MDQ+ Premium"
  //            Footer: Cancel Subscription button
  //
  //  State B — Family Host      tier == 'family' && isFamilyAdmin == true
  //            Title : "MDQ+ Family Plan (Host)"
  //            Footer: Cancel Subscription button
  //
  //  State C — Family Dependent tier == 'family' && isFamilyAdmin == false
  //            Title : "MDQ+ Family Plan (Dependent)"
  //            Footer: "Billing is managed by your Family Host." (no cancel)

  void _showManageSubscriptionModal(BuildContext context, WidgetRef ref, User user) {
    // ── Derive the three states ───────────────────────────────────────────────
    final bool isFamilyTier  = user.subscriptionTier == 'family';
    final bool isFamilyHost  = isFamilyTier && user.isFamilyAdmin;
    final bool isFamilyDep   = isFamilyTier && !user.isFamilyAdmin;

    // Plan label: precise enough to tell users exactly what they are on.
    final String planLabel = isFamilyHost
        ? 'MDQ+ Family Plan (Host)'
        : isFamilyDep
            ? 'MDQ+ Family Plan (Dependent)'
            : 'MDQ+ Premium';

    // Accent colour: gold for family tiers, brand blue for premium.
    final Color accentColor =
        isFamilyTier ? const Color(0xFFD4AF37) : const Color(0xFF4A90E2);

    // Role badge label shown below the plan name.
    final String? roleBadge = isFamilyHost
        ? 'Host · Billing owner'
        : isFamilyDep
            ? 'Dependent · Shared access'
            : null;

    final bool isCancelled = !isFamilyDep && !user.autoRenew && (user.subscriptionTier == 'premium' || user.subscriptionTier == 'family');

    // Only active hosts and solo-premium users can cancel.
    final bool canCancel = !isFamilyDep && !isCancelled;
    bool isCancelling = false;

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(16))),
      builder: (sheetCtx) {
        return StatefulBuilder(
          builder: (sheetCtx, setSheetState) {
            return Padding(
          padding: const EdgeInsets.fromLTRB(24, 24, 24, 36),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // ── Sheet header ────────────────────────────────────────────
              Text('Manage Subscription',
                  style: Theme.of(sheetCtx).textTheme.titleLarge),
              const SizedBox(height: 16),

              // ── Plan info card ──────────────────────────────────────────
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: accentColor.withOpacity(0.08),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: accentColor.withOpacity(0.35)),
                ),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon(
                      isFamilyTier ? Icons.family_restroom : Icons.verified,
                      color: accentColor,
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          // Plan name
                          Text(
                            planLabel,
                            style: TextStyle(
                              fontWeight: FontWeight.bold,
                              fontSize: 15,
                              color: accentColor,
                            ),
                          ),
                          // Role badge (only for family tiers)
                          if (roleBadge != null) ...[
                            const SizedBox(height: 4),
                            Container(
                              padding: const EdgeInsets.symmetric(
                                  horizontal: 8, vertical: 3),
                              decoration: BoxDecoration(
                                color: accentColor.withOpacity(0.12),
                                borderRadius: BorderRadius.circular(20),
                              ),
                              child: Text(
                                roleBadge,
                                style: TextStyle(
                                  fontSize: 11,
                                  fontWeight: FontWeight.w600,
                                  color: accentColor,
                                ),
                              ),
                            ),
                          ],
                          const SizedBox(height: 6),
                          Text(
                            'Your plan is currently active.',
                            style: TextStyle(
                                color: Colors.grey[600], fontSize: 13),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 24),

              // ── State C: dependent info notice (no cancel button) ────────
              if (isFamilyDep)
                Container(
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: Colors.grey.withOpacity(0.08),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: Colors.grey.withOpacity(0.25)),
                  ),
                  child: Row(
                    children: [
                      const Icon(Icons.info_outline_rounded,
                          size: 18, color: Colors.grey),
                      const SizedBox(width: 10),
                      const Expanded(
                        child: Text(
                          'Billing is managed by your Family Host. '
                          'Contact them to make changes to the plan.',
                          style: TextStyle(fontSize: 13, color: Colors.grey),
                        ),
                      ),
                    ],
                  ),
                ),

              // ── Cancelled state ──────────────────────────────────────────
              if (isCancelled)
                Container(
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: Colors.orange.withOpacity(0.08),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: Colors.orange.withOpacity(0.3)),
                  ),
                  child: Row(
                    children: [
                      const Icon(Icons.info_outline_rounded,
                          size: 18, color: Colors.orange),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          'Subscription Cancelled. Access remains until ${user.subscriptionExpiry?.split('T')[0] ?? "the end of your billing cycle"}.',
                          style: const TextStyle(fontSize: 13, color: Colors.orange),
                        ),
                      ),
                    ],
                  ),
                ),

              // ── States A & B: cancel button ──────────────────────────────
              if (canCancel)
                OutlinedButton.icon(
                  icon: isCancelling
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.red,
                          ),
                        )
                      : const Icon(Icons.cancel_outlined, color: Colors.red),
                  label: Text(
                    isCancelling ? 'Cancelling...' : 'Cancel Subscription',
                    style: const TextStyle(
                        color: Colors.red, fontWeight: FontWeight.w600),
                  ),
                  style: OutlinedButton.styleFrom(
                    side: const BorderSide(color: Colors.red),
                    padding: const EdgeInsets.symmetric(vertical: 14),
                    shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(10)),
                  ),
                  onPressed: isCancelling
                      ? null
                      : () async {
                    // Snapshot the messenger from the OUTER (ProfileScreen)
                    // context before any pop. The sheet context (sheetCtx) will
                    // be unmounted the moment we pop it, so we must not use it
                    // for anything that runs asynchronously afterward.
                    final messenger = ScaffoldMessenger.of(context);

                    // Use the outer `context` (ProfileScreen – always mounted)
                    // for the confirmation dialog.
                    if (!context.mounted) return;
                    final confirm = await showDialog<bool>(
                      context: context,
                      builder: (dialogCtx) => AlertDialog(
                        title: const Text('Cancel Subscription'),
                        content: const Text(
                            'Are you sure you want to cancel your subscription? '
                            'You will retain access to all premium features until '
                            'your current billing cycle expires.'),
                        actions: [
                          TextButton(
                            onPressed: () =>
                                Navigator.of(dialogCtx).pop(false),
                            child: const Text('No'),
                          ),
                          TextButton(
                            onPressed: () =>
                                Navigator.of(dialogCtx).pop(true),
                            child: const Text('Yes',
                                style: TextStyle(color: Colors.red)),
                          ),
                        ],
                      ),
                    );

                    if (confirm != true) return;
                    setSheetState(() => isCancelling = true);

                    try {
                      await ref
                          .read(authControllerProvider.notifier)
                          .cancelSubscription();

                      // Explicitly invalidate so ProfileScreen always rebuilds
                      // with the downgraded tier, even if the controller's
                      // internal invalidate was skipped due to Ref lifecycle.
                      ref.invalidate(userProvider);

                      if (sheetCtx.mounted) Navigator.of(sheetCtx).pop();
                      messenger.showSnackBar(
                        const SnackBar(
                            content:
                                Text('Subscription cancelled successfully'),
                            backgroundColor: Colors.green),
                      );
                    } catch (e) {
                      if (sheetCtx.mounted) {
                        setSheetState(() => isCancelling = false);
                      }
                      messenger.showSnackBar(
                        SnackBar(
                            content: Text(e.toString()),
                            backgroundColor: Colors.red),
                      );
                    }
                  },
                ),
            ],
          ),
        );
          },
        );
      },
    );
  }

  // ── Contact Support modal ─────────────────────────────────────────────────

  void _showSupportModal(BuildContext context, WidgetRef ref) {
    final subjectController = TextEditingController();
    final messageController = TextEditingController();
    bool isLoading = false;

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(16))),
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
                  Text("Contact Support",
                      style: Theme.of(context).textTheme.titleLarge),
                  const SizedBox(height: 16),
                  TextField(
                    controller: subjectController,
                    decoration: const InputDecoration(
                        labelText: "Subject",
                        border: OutlineInputBorder()),
                  ),
                  const SizedBox(height: 16),
                  TextField(
                    controller: messageController,
                    minLines: 3,
                    maxLines: 5,
                    decoration: const InputDecoration(
                        labelText: "Message",
                        border: OutlineInputBorder()),
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
                              await ref
                                  .read(authControllerProvider.notifier)
                                  .sendSupportMessage(
                                      subject: subject, message: message);
                              if (context.mounted) {
                                Navigator.pop(context);
                                ScaffoldMessenger.of(context).showSnackBar(
                                  const SnackBar(
                                      content: Text(
                                          "Message sent successfully. We will get back to you soon."),
                                      backgroundColor: Colors.green),
                                );
                              }
                            } catch (e) {
                              if (context.mounted) {
                                ScaffoldMessenger.of(context).showSnackBar(
                                  SnackBar(
                                      content: Text(e.toString()),
                                      backgroundColor: Colors.red),
                                );
                              }
                            } finally {
                              if (context.mounted) {
                                setState(() => isLoading = false);
                              }
                            }
                          },
                    child: isLoading
                        ? const SizedBox(
                            height: 20,
                            width: 20,
                            child: CircularProgressIndicator(strokeWidth: 2))
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
