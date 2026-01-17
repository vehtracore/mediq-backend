import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';
import 'package:mediq_app/src/features/appointments/data/appointment_model.dart';
import 'package:mediq_app/src/features/appointments/data/appointment_repository.dart';

class PaymentScreen extends ConsumerStatefulWidget {
  final Appointment appointment;
  final double amount;

  const PaymentScreen({
    super.key,
    required this.appointment,
    required this.amount,
  });

  @override
  ConsumerState<PaymentScreen> createState() => _PaymentScreenState();
}

class _PaymentScreenState extends ConsumerState<PaymentScreen> {
  final _formKey = GlobalKey<FormState>();
  bool _isLoading = false;
  int _selectedMethod = 0; // 0 = Card, 1 = Transfer

  // Mock Controllers
  final _cardNumCtrl = TextEditingController();
  final _expiryCtrl = TextEditingController();
  final _cvvCtrl = TextEditingController();

  @override
  void dispose() {
    _cardNumCtrl.dispose();
    _expiryCtrl.dispose();
    _cvvCtrl.dispose();
    super.dispose();
  }

  Future<void> _processPayment() async {
    // If Card mode, validate fields
    if (_selectedMethod == 0 && !_formKey.currentState!.validate()) return;

    setState(() => _isLoading = true);
    await Future.delayed(const Duration(seconds: 2)); // Mock delay

    try {
      // ✅ FIX: Reverted to 'markAsPaid' which exists in your repository
      await ref
          .read(appointmentRepositoryProvider)
          .markAsPaid(widget.appointment.id);

      if (mounted) {
        showDialog(
          context: context,
          barrierDismissible: false,
          builder: (ctx) => AlertDialog(
            backgroundColor: Theme.of(context).cardColor,
            shape:
                RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
            content: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.check_circle, color: Colors.green, size: 60),
                const SizedBox(height: 16),
                Text("Payment Successful!",
                    style: Theme.of(context)
                        .textTheme
                        .titleLarge
                        ?.copyWith(fontWeight: FontWeight.bold)),
                const SizedBox(height: 8),
                const Text("Your appointment has been confirmed."),
              ],
            ),
            actions: [
              TextButton(
                  onPressed: () => context.go('/schedule'),
                  child: const Text("Go to Schedule")),
            ],
          ),
        );
      }
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text("Payment Failed: $e")));
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;

    return Scaffold(
      backgroundColor: theme.scaffoldBackgroundColor, // ✅ Dynamic
      appBar: AppBar(
        title: const Text("Secure Checkout"),
        backgroundColor: theme.appBarTheme.backgroundColor,
        foregroundColor: theme.appBarTheme.foregroundColor,
        elevation: 0,
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              padding: const EdgeInsets.all(20),
              decoration: BoxDecoration(
                gradient: const LinearGradient(
                    colors: [Color(0xFF4A90E2), Color(0xFF50E3C2)]),
                borderRadius: BorderRadius.circular(16),
              ),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  const Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text("Total Amount",
                          style: TextStyle(color: Colors.white70)),
                      SizedBox(height: 4),
                      Text("Consultation Fee",
                          style: TextStyle(
                              color: Colors.white,
                              fontWeight: FontWeight.bold,
                              fontSize: 16)),
                    ],
                  ),
                  Text("₦${NumberFormat('#,###').format(widget.amount)}",
                      style: const TextStyle(
                          color: Colors.white,
                          fontSize: 24,
                          fontWeight: FontWeight.bold)),
                ],
              ),
            ),
            const SizedBox(height: 32),
            Text("Payment Method",
                style: theme.textTheme.titleMedium
                    ?.copyWith(fontWeight: FontWeight.bold)),
            const SizedBox(height: 16),
            Row(
              children: [
                _buildMethodTab(
                    0, "Credit/Debit Card", Icons.credit_card, theme),
                const SizedBox(width: 12),
                _buildMethodTab(
                    1, "Bank Transfer", Icons.account_balance, theme),
              ],
            ),
            const SizedBox(height: 32),
            if (_selectedMethod == 0)
              _buildCardForm(theme)
            else
              _buildTransferDetails(theme),
            const SizedBox(height: 40),
            SizedBox(
              width: double.infinity,
              height: 50,
              child: ElevatedButton(
                onPressed: _isLoading ? null : _processPayment,
                style: ElevatedButton.styleFrom(
                  backgroundColor: const Color(0xFF4A90E2),
                  foregroundColor: Colors.white,
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12)),
                ),
                child: _isLoading
                    ? const CircularProgressIndicator(color: Colors.white)
                    : Text(
                        "Pay ₦${NumberFormat('#,###').format(widget.amount)}",
                        style: const TextStyle(
                            fontSize: 16, fontWeight: FontWeight.bold)),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildMethodTab(
      int index, String label, IconData icon, ThemeData theme) {
    final isSelected = _selectedMethod == index;
    final isDark = theme.brightness == Brightness.dark;

    return Expanded(
      child: GestureDetector(
        onTap: () => setState(() => _selectedMethod = index),
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 12),
          decoration: BoxDecoration(
            color: isSelected
                ? const Color(0xFF4A90E2)
                : theme.cardTheme.color, // ✅ Dynamic
            borderRadius: BorderRadius.circular(12),
            border: Border.all(
                color: isSelected
                    ? const Color(0xFF4A90E2)
                    : (isDark ? Colors.grey[700]! : Colors.grey[300]!)),
          ),
          child: Column(
            children: [
              Icon(icon, color: isSelected ? Colors.white : Colors.grey),
              const SizedBox(height: 4),
              Text(label,
                  style: TextStyle(
                      color: isSelected ? Colors.white : Colors.grey,
                      fontWeight: FontWeight.bold,
                      fontSize: 12)),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildCardForm(ThemeData theme) {
    return Form(
      key: _formKey,
      child: Column(
        children: [
          TextFormField(
            controller: _cardNumCtrl,
            style: theme.textTheme.bodyLarge, // ✅ Dynamic Input
            decoration: _inputDecoration("Card Number", Icons.numbers, theme),
            keyboardType: TextInputType.number,
            validator: (v) => v!.isEmpty ? "Required" : null,
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                  child: TextFormField(
                      controller: _expiryCtrl,
                      style: theme.textTheme.bodyLarge,
                      decoration: _inputDecoration(
                          "MM/YY", Icons.calendar_today, theme),
                      validator: (v) => v!.isEmpty ? "Required" : null)),
              const SizedBox(width: 16),
              Expanded(
                  child: TextFormField(
                      controller: _cvvCtrl,
                      obscureText: true,
                      style: theme.textTheme.bodyLarge,
                      decoration: _inputDecoration("CVV", Icons.lock, theme),
                      validator: (v) => v!.isEmpty ? "Required" : null)),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildTransferDetails(ThemeData theme) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
          color: Colors.orange.withOpacity(0.1),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: Colors.orange.withOpacity(0.3))),
      child: Column(
        children: [
          const Text("Transfer to this account:",
              style:
                  TextStyle(color: Colors.orange, fontWeight: FontWeight.bold)),
          const SizedBox(height: 8),
          Text("MDQ Health Ltd",
              style: theme.textTheme.titleMedium
                  ?.copyWith(fontWeight: FontWeight.bold)),
          const Text("1234567890",
              style: TextStyle(
                  fontSize: 24, fontWeight: FontWeight.bold, letterSpacing: 2)),
          const Text("GTBank", style: TextStyle(color: Colors.grey)),
          const SizedBox(height: 16),
          const Text("Click 'Pay' after transfer is complete.",
              style: TextStyle(fontSize: 12, fontStyle: FontStyle.italic)),
        ],
      ),
    );
  }

  InputDecoration _inputDecoration(
      String hint, IconData icon, ThemeData theme) {
    final isDark = theme.brightness == Brightness.dark;
    return InputDecoration(
      hintText: hint,
      prefixIcon: Icon(icon, color: Colors.grey),
      filled: true,
      fillColor: theme.inputDecorationTheme.fillColor, // ✅ Dynamic Fill
      hintStyle: TextStyle(color: Colors.grey[400]),
      border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12), borderSide: BorderSide.none),
    );
  }
}
