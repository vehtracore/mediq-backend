import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../auth/presentation/user_controller.dart';
import '../../auth/data/auth_repository.dart';

class SubscriptionScreen extends ConsumerStatefulWidget {
  const SubscriptionScreen({super.key});

  @override
  ConsumerState<SubscriptionScreen> createState() => _SubscriptionScreenState();
}

class _SubscriptionScreenState extends ConsumerState<SubscriptionScreen> {
  Future<void> _handleSubscribe(
      {required String planTitle,
      required double parsedPrice,
      required bool isFamily}) async {
    final user = ref.read(userProvider).value;
    await context.push('/payment', extra: {
      'transactionType': isFamily ? 'family_subscription' : 'subscription',
      'baseAmount': parsedPrice,
      'title': planTitle,
      'userId': user?.id,
    });
    ref.invalidate(userProvider);
  }

  void _showJoinFamilyDialog() {
    final TextEditingController codeController = TextEditingController();
    bool isSubmitting = false;

    showDialog(
      context: context,
      builder: (context) {
        return StatefulBuilder(
          builder: (context, setState) {
            return AlertDialog(
              title: const Text('Join Family Plan'),
              content: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Text(
                      'Enter the invite code from your family administrator.'),
                  const SizedBox(height: 16),
                  TextField(
                    controller: codeController,
                    decoration: const InputDecoration(
                      labelText: 'Invite Code',
                      border: OutlineInputBorder(),
                    ),
                  ),
                ],
              ),
              actions: [
                TextButton(
                  onPressed: isSubmitting ? null : () => Navigator.pop(context),
                  child: const Text('Cancel'),
                ),
                ElevatedButton(
                  onPressed: isSubmitting
                      ? null
                      : () async {
                          final code = codeController.text.trim();
                          if (code.isEmpty) return;

                          setState(() => isSubmitting = true);

                          try {
                            await ref
                                .read(authRepositoryProvider)
                                .joinFamily(code);
                            if (!context.mounted) return;

                            // Refresh user state
                            ref.invalidate(userProvider);

                            Navigator.pop(context);
                            ScaffoldMessenger.of(context).showSnackBar(
                              const SnackBar(
                                  content: Text(
                                      'Successfully joined the family plan!')),
                            );
                            // Optionally redirect to patient home
                            context.go('/patient_home');
                          } catch (e) {
                            if (!context.mounted) return;
                            setState(() => isSubmitting = false);
                            ScaffoldMessenger.of(context).showSnackBar(
                              SnackBar(
                                  content: Text(e
                                      .toString()
                                      .replaceAll('Exception: ', ''))),
                            );
                          }
                        },
                  child: isSubmitting
                      ? const SizedBox(
                          width: 20,
                          height: 20,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Text('Join'),
                ),
              ],
            );
          },
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final user = ref.watch(userProvider).value;
    final isFamilyUser = user?.subscriptionTier == 'family';
    final isPremium = user?.isPremium ?? false;
    final theme = Theme.of(context);

    if (isFamilyUser) {
      return Scaffold(
        backgroundColor: theme.scaffoldBackgroundColor,
        appBar: AppBar(
          title: const Text("Subscription"),
          backgroundColor: theme.appBarTheme.backgroundColor,
          foregroundColor: theme.appBarTheme.foregroundColor,
          elevation: 0,
        ),
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(32.0),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const Icon(Icons.family_restroom,
                    size: 64, color: Color(0xFFD4AF37)),
                const SizedBox(height: 24),
                Text(
                  "You are on the Family Plan",
                  style: theme.textTheme.headlineSmall
                      ?.copyWith(fontWeight: FontWeight.bold),
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 16),
                Text(
                  "Enjoy Premium features and unlimited everyday AI support for each family member, subject to fair use.",
                  style: theme.textTheme.bodyMedium,
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 32),
                if (user?.isFamilyAdmin ?? false)
                  ElevatedButton.icon(
                    onPressed: () => context.push('/family_dashboard'),
                    icon: const Icon(Icons.dashboard),
                    label: const Text("Go to Family Dashboard"),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: const Color(0xFFD4AF37),
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(
                          horizontal: 24, vertical: 16),
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(12)),
                    ),
                  ),
              ],
            ),
          ),
        ),
      );
    }

    return Scaffold(
      backgroundColor: theme.scaffoldBackgroundColor, // ✅ Dynamic
      appBar: AppBar(
        title: const Text("Subscription"),
        backgroundColor: theme.appBarTheme.backgroundColor,
        foregroundColor: theme.appBarTheme.foregroundColor,
        elevation: 0,
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Column(
          children: [
            _buildPlanCard(
              context,
              title: "Free Plan",
              price: "₦0/mo",
              features: [
                "Limited AI chats per month",
                "Standard Doctor Booking",
                "Basic Health Tips"
              ],
              isCurrent: !isPremium,
              theme: theme,
            ),
            const SizedBox(height: 24),
            _buildPlanCard(
              context,
              title: "MDQ+ Premium",
              price: "₦3,500/mo",
              features: [
                "Unlimited everyday AI support*",
                "Priority Doctor Access",
                "10 AI photo/lab interpretations monthly",
                "Advanced Health Analytics",
                "Consultation Summaries"
              ],
              isCurrent: isPremium,
              isPremium: true,
              theme: theme,
            ),
            const SizedBox(height: 24),
            _buildPlanCard(
              context,
              title: "Family Plan",
              price: "₦10,000/mo",
              features: [
                "4 Independent Private Accounts",
                "Unlimited everyday AI support per account*",
                "10 AI photo/lab interpretations per account",
                "Private Medical Records for each",
                "All MDQ+ Premium Features",
                "Centralized Billing"
              ],
              isCurrent: false,
              isPremium: true,
              isFamily: true,
              theme: theme,
            ),
            const SizedBox(height: 32),
            TextButton(
              onPressed: _showJoinFamilyDialog,
              child: const Text(
                "Have a family invite code? Join here.",
                style: TextStyle(decoration: TextDecoration.underline),
              ),
            ),
            const SizedBox(height: 10),
            Text(
              'Subscriptions automatically renew unless cancelled. *AI access is subject to fair use. Terms and conditions apply.',
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: 10.5,
                color: Colors.grey[500],
                height: 1.35,
              ),
            ),
            const SizedBox(height: 16),
          ],
        ),
      ),
    );
  }

  Widget _buildPlanCard(
    BuildContext context, {
    required String title,
    required String price,
    required List<String> features,
    bool isCurrent = false,
    bool isPremium = false,
    bool isFamily = false,
    required ThemeData theme,
  }) {
    final isDark = theme.brightness == Brightness.dark;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: theme.cardTheme.color, // ✅ Dynamic
        borderRadius: BorderRadius.circular(20),
        border: isFamily
            ? Border.all(color: const Color(0xFFD4AF37), width: 2.5)
            : (isPremium && !isDark
                ? Border.all(color: const Color(0xFF4A90E2), width: 2)
                : null),
        boxShadow: isDark
            ? []
            : [
                BoxShadow(
                    color: Colors.grey.withValues(alpha: 0.1),
                    blurRadius: 20,
                    offset: const Offset(0, 10))
              ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (isFamily)
            Container(
              margin: const EdgeInsets.only(bottom: 12),
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
              decoration: BoxDecoration(
                gradient: const LinearGradient(
                  colors: [Color(0xFFD4AF37), Color(0xFFF5D76E)],
                ),
                borderRadius: BorderRadius.circular(20),
              ),
              child: const Text(
                '⭐ Best Value',
                style: TextStyle(
                    color: Colors.white,
                    fontWeight: FontWeight.bold,
                    fontSize: 12),
              ),
            ),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(title,
                  style: TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.bold,
                      color: isFamily
                          ? const Color(0xFFD4AF37)
                          : (isPremium
                              ? const Color(0xFF4A90E2)
                              : theme.textTheme.bodyLarge?.color))),
              if (isCurrent) const Icon(Icons.check_circle, color: Colors.grey),
            ],
          ),
          const SizedBox(height: 8),
          Text(price,
              style: theme.textTheme.headlineSmall
                  ?.copyWith(fontWeight: FontWeight.bold)),
          const SizedBox(height: 24),
          ...features.map((f) => Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Row(
                  children: [
                    Icon(Icons.check,
                        size: 18,
                        color:
                            isPremium ? const Color(0xFF50E3C2) : Colors.grey),
                    const SizedBox(width: 12),
                    Text(f, style: theme.textTheme.bodyMedium),
                  ],
                ),
              )),
          const SizedBox(height: 24),
          SizedBox(
            width: double.infinity,
            height: 50,
            child: isCurrent
                ? const OutlinedButton(
                    onPressed: null, child: Text("Current Plan"))
                : ElevatedButton(
                    onPressed: () {
                      // Parse the numeric value from price string e.g. "₦2,500/mo" → 2500.0
                      final parsedPrice = double.tryParse(
                            price
                                .replaceAll('₦', '')
                                .replaceAll(',', '')
                                .split('/')
                                .first
                                .trim(),
                          ) ??
                          0.0;
                      _handleSubscribe(
                        planTitle: title,
                        parsedPrice: parsedPrice,
                        isFamily: isFamily,
                      );
                    },
                    style: ElevatedButton.styleFrom(
                      backgroundColor:
                          isPremium ? const Color(0xFF4A90E2) : Colors.grey,
                      foregroundColor: Colors.white,
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(12)),
                    ),
                    child: const Text("Upgrade Now"),
                  ),
          ),
        ],
      ),
    );
  }
}
