import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../auth/presentation/user_controller.dart';

class SubscriptionScreen extends ConsumerStatefulWidget {
  const SubscriptionScreen({super.key});

  @override
  ConsumerState<SubscriptionScreen> createState() => _SubscriptionScreenState();
}

class _SubscriptionScreenState extends ConsumerState<SubscriptionScreen> {
  final bool _isLoading = false;

  void _handleSubscribe({required String planTitle, required double parsedPrice, required bool isFamily}) {
    final user = ref.read(userProvider).value;
    context.push('/payment', extra: {
      'transactionType': isFamily ? 'family_subscription' : 'subscription',
      'baseAmount': parsedPrice,
      'title': planTitle,
      'userId': user?.id,
    });
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
                "Urinalysis AI",
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
                "4 Independent Premium Accounts",
                "Private Medical Records for each",
                "All MDQ+ Premium Features",
                "Centralized Billing"
              ],
              isCurrent: false,
              isPremium: true,
              isFamily: true,
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
                    color: Colors.grey.withOpacity(0.1),
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
                                .split('/').first
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
