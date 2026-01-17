import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../auth/data/auth_repository.dart';
import '../../auth/presentation/user_controller.dart';

class SubscriptionScreen extends ConsumerStatefulWidget {
  const SubscriptionScreen({super.key});

  @override
  ConsumerState<SubscriptionScreen> createState() => _SubscriptionScreenState();
}

class _SubscriptionScreenState extends ConsumerState<SubscriptionScreen> {
  bool _isLoading = false;

  Future<void> _handleSubscribe() async {
    setState(() => _isLoading = true);
    try {
      await ref.read(authRepositoryProvider).upgradeToPremium();
      ref.invalidate(userProvider);
      if (!mounted) return;
      showDialog(
        context: context,
        barrierDismissible: false,
        builder: (ctx) => AlertDialog(
          backgroundColor: Theme.of(context).cardColor,
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
          content: const Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.star_rounded, color: Colors.amber, size: 60),
              SizedBox(height: 16),
              Text("Welcome to Premium!",
                  style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
              SizedBox(height: 8),
              Text(
                  "You now have unlimited AI chats and priority doctor access.",
                  textAlign: TextAlign.center),
            ],
          ),
          actions: [
            TextButton(
                onPressed: () {
                  Navigator.pop(ctx);
                  context.pop();
                },
                child: const Text("Awesome!")),
          ],
        ),
      );
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text("Failed: $e")));
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final user = ref.watch(userProvider).value;
    final isPremium = user?.subscriptionTier == 'premium';
    final theme = Theme.of(context);

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
                "3 AI Chats per day",
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
              price: "₦2,500/mo",
              features: [
                "Unlimited AI Chats",
                "Priority Doctor Access",
                "Video Consultations",
                "Advanced Health Analytics"
              ],
              isCurrent: isPremium,
              isPremium: true,
              theme: theme,
            ),
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
    required ThemeData theme,
  }) {
    final isDark = theme.brightness == Brightness.dark;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: theme.cardTheme.color, // ✅ Dynamic
        borderRadius: BorderRadius.circular(20),
        border: isPremium && !isDark
            ? Border.all(color: const Color(0xFF4A90E2), width: 2)
            : null,
        boxShadow: isDark
            ? []
            : [
                BoxShadow(
                    color: Colors.grey.withOpacity(0.1),
                    blurRadius: 20,
                    offset: const Offset(0, 10))
              ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(title,
                  style: TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.bold,
                      color: isPremium
                          ? const Color(0xFF4A90E2)
                          : theme.textTheme.bodyLarge?.color)),
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
                ? OutlinedButton(
                    onPressed: null, child: const Text("Current Plan"))
                : ElevatedButton(
                    onPressed: _isLoading ? null : _handleSubscribe,
                    style: ElevatedButton.styleFrom(
                      backgroundColor:
                          isPremium ? const Color(0xFF4A90E2) : Colors.grey,
                      foregroundColor: Colors.white,
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(12)),
                    ),
                    child: _isLoading
                        ? const CircularProgressIndicator(color: Colors.white)
                        : const Text("Upgrade Now"),
                  ),
          ),
        ],
      ),
    );
  }
}
