import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../auth/data/auth_repository.dart';
import '../../auth/presentation/user_controller.dart'; // To refresh user profile

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
      // 1. Call API
      await ref.read(authRepositoryProvider).upgradeToPremium();

      // 2. Refresh User Provider (to update UI across the app)
      ref.invalidate(userProvider);

      if (!mounted) return;

      // 3. Show Success & Close
      showDialog(
        context: context,
        barrierDismissible: false,
        builder: (ctx) => AlertDialog(
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(20),
          ),
          content: const Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.star_rounded, color: Colors.amber, size: 60),
              SizedBox(height: 16),
              Text(
                "Welcome to Premium!",
                style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold),
              ),
              SizedBox(height: 8),
              Text(
                "You now have unlimited chats and discounted consultations.",
                textAlign: TextAlign.center,
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () {
                Navigator.pop(ctx); // Close Dialog
                context.pop(); // Close Screen
              },
              child: const Text("Awesome"),
            ),
          ],
        ),
      );
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text("Error: $e"), backgroundColor: Colors.red),
        );
      }
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF9FAFB),
      appBar: AppBar(
        backgroundColor: Colors.white,
        elevation: 0,
        iconTheme: const IconThemeData(color: Colors.black),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24.0),
        child: Column(
          children: [
            // --- Header ---
            const Icon(
              Icons.workspace_premium,
              size: 60,
              color: Color(0xFF4A90E2),
            ),
            const SizedBox(height: 16),
            const Text(
              "Upgrade to MedIQ Plus",
              style: TextStyle(
                fontSize: 24,
                fontWeight: FontWeight.bold,
                color: Color(0xFF2D3436),
              ),
            ),
            const SizedBox(height: 8),
            const Text(
              "Unlock the full power of AI healthcare",
              style: TextStyle(color: Colors.grey, fontSize: 16),
            ),
            const SizedBox(height: 40),

            // --- Free Plan (Current) ---
            _buildPlanCard(
              title: "Basic Plan",
              price: "Free",
              features: [
                "5 AI Health Chats / Day",
                "Standard Queue for GPs",
                "Full Price Consultations (NGN 4,000)",
              ],
              isCurrent: true,
            ),

            const SizedBox(height: 24),

            // --- Premium Plan (Target) ---
            Stack(
              clipBehavior: Clip.none,
              children: [
                _buildPlanCard(
                  title: "MedIQ Plus",
                  price: "NGN 2,500 / month",
                  features: [
                    "Unlimited AI Health Chats",
                    "Priority Access to GPs",
                    "Discounted Consults (NGN 2,500)",
                    "Image Analysis (Coming Soon)",
                  ],
                  isPremium: true,
                ),
                Positioned(
                  top: -12,
                  right: 20,
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 12,
                      vertical: 4,
                    ),
                    decoration: BoxDecoration(
                      color: Colors.amber,
                      borderRadius: BorderRadius.circular(20),
                    ),
                    child: const Text(
                      "Recommended",
                      style: TextStyle(
                        color: Colors.black,
                        fontSize: 12,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ),
                ),
              ],
            ),

            const SizedBox(height: 40),

            // --- Subscribe Button ---
            SizedBox(
              width: double.infinity,
              height: 54,
              child: ElevatedButton(
                onPressed: _isLoading ? null : _handleSubscribe,
                style: ElevatedButton.styleFrom(
                  backgroundColor: const Color(0xFF4A90E2),
                  foregroundColor: Colors.white,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(16),
                  ),
                  elevation: 4,
                  shadowColor: const Color(0xFF4A90E2).withOpacity(0.4),
                ),
                child: _isLoading
                    ? const CircularProgressIndicator(color: Colors.white)
                    : const Text(
                        "Subscribe Now",
                        style: TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
              ),
            ),
            const SizedBox(height: 16),
            const Text(
              "Cancel anytime. Secure payment via Paystack (Mock).",
              style: TextStyle(color: Colors.grey, fontSize: 12),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildPlanCard({
    required String title,
    required String price,
    required List<String> features,
    bool isCurrent = false,
    bool isPremium = false,
  }) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(20),
        border: isPremium
            ? Border.all(color: const Color(0xFF4A90E2), width: 2)
            : Border.all(color: Colors.grey.withOpacity(0.2)),
        boxShadow: isPremium
            ? [
                BoxShadow(
                  color: const Color(0xFF4A90E2).withOpacity(0.15),
                  blurRadius: 20,
                  offset: const Offset(0, 10),
                ),
              ]
            : [],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                title,
                style: TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.bold,
                  color: isPremium ? const Color(0xFF4A90E2) : Colors.black,
                ),
              ),
              if (isCurrent) const Icon(Icons.check_circle, color: Colors.grey),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            price,
            style: const TextStyle(fontSize: 22, fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 24),
          ...features.map(
            (f) => Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Row(
                children: [
                  Icon(
                    Icons.check,
                    size: 18,
                    color: isPremium ? const Color(0xFF50E3C2) : Colors.grey,
                  ),
                  const SizedBox(width: 12),
                  Text(f, style: const TextStyle(fontSize: 14)),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
