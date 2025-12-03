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
    // If Card mode, validate fields. If Transfer, skip validation.
    if (_selectedMethod == 0 && !_formKey.currentState!.validate()) return;

    setState(() => _isLoading = true);

    try {
      // 1. Simulate Network Delay
      await Future.delayed(const Duration(seconds: 2));

      // 2. Call Backend
      await ref
          .read(appointmentRepositoryProvider)
          .markAsPaid(widget.appointment.id);

      if (!mounted) return;

      // 3. Success
      showDialog(
        context: context,
        barrierDismissible: false,
        builder: (ctx) => AlertDialog(
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(20),
          ),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.check_circle, color: Colors.green, size: 60),
              const SizedBox(height: 16),
              const Text(
                "Payment Successful!",
                style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 8),
              Text(
                "Transaction ID: PAY-${DateTime.now().millisecondsSinceEpoch}",
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => context.go('/patient_home'),
              child: const Text("Go to Dashboard"),
            ),
          ],
        ),
      );
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(e.toString()), backgroundColor: Colors.red),
      );
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final dateStr = DateFormat(
      'MMM dd, yyyy - h:mm a',
    ).format(widget.appointment.startTime);

    return Scaffold(
      backgroundColor: const Color(0xFFF9FAFB),
      appBar: AppBar(
        title: const Text(
          "Secure Checkout",
          style: TextStyle(color: Colors.black),
        ),
        backgroundColor: Colors.white,
        elevation: 0,
        iconTheme: const IconThemeData(color: Colors.black),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24.0),
        child: Column(
          children: [
            // --- Summary Card ---
            Container(
              padding: const EdgeInsets.all(20),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(16),
                boxShadow: [
                  BoxShadow(
                    color: Colors.grey.withOpacity(0.1),
                    blurRadius: 10,
                  ),
                ],
              ),
              child: Column(
                children: [
                  Text(
                    "NGN ${widget.amount.toStringAsFixed(2)}",
                    style: const TextStyle(
                      fontSize: 32,
                      fontWeight: FontWeight.bold,
                      color: Color(0xFF4A90E2),
                    ),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    "Consultation with ${widget.appointment.doctorName}",
                    style: const TextStyle(fontWeight: FontWeight.w500),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    dateStr,
                    style: TextStyle(color: Colors.grey[600], fontSize: 13),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 32),

            // --- Payment Methods Toggle ---
            Row(
              children: [
                _buildMethodTab(0, "Card", Icons.credit_card),
                const SizedBox(width: 16),
                _buildMethodTab(1, "Bank Transfer", Icons.account_balance),
              ],
            ),
            const SizedBox(height: 24),

            // --- Payment Details ---
            if (_selectedMethod == 0)
              Form(
                key: _formKey,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      "Card Details",
                      style: TextStyle(fontWeight: FontWeight.bold),
                    ),
                    const SizedBox(height: 12),
                    TextFormField(
                      controller: _cardNumCtrl,
                      keyboardType: TextInputType.number,
                      decoration: _inputDecoration(
                        "Card Number",
                        Icons.credit_card,
                      ),
                      validator: (v) => v!.isEmpty ? "Required" : null,
                    ),
                    const SizedBox(height: 16),
                    Row(
                      children: [
                        Expanded(
                          child: TextFormField(
                            controller: _expiryCtrl,
                            keyboardType: TextInputType.datetime,
                            decoration: _inputDecoration(
                              "MM/YY",
                              Icons.calendar_today,
                            ),
                            validator: (v) => v!.isEmpty ? "Required" : null,
                          ),
                        ),
                        const SizedBox(width: 16),
                        Expanded(
                          child: TextFormField(
                            controller: _cvvCtrl,
                            keyboardType: TextInputType.number,
                            obscureText: true,
                            decoration: _inputDecoration(
                              "CVV",
                              Icons.lock_outline,
                            ),
                            validator: (v) => v!.isEmpty ? "Required" : null,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              )
            else
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: Colors.orange.withOpacity(0.1),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: Colors.orange.withOpacity(0.3)),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: const [
                    Text(
                      "Transfer to:",
                      style: TextStyle(fontWeight: FontWeight.bold),
                    ),
                    SizedBox(height: 8),
                    Text("Bank: Zenith Bank"),
                    Text("Acct: 1234567890"),
                    Text("Name: MedIQ Health Ltd"),
                    SizedBox(height: 16),
                    Text(
                      "Click 'I have made the transfer' below to confirm.",
                      style: TextStyle(fontSize: 12, color: Colors.grey),
                    ),
                  ],
                ),
              ),

            const SizedBox(height: 40),

            // --- Pay Button ---
            SizedBox(
              width: double.infinity,
              height: 52,
              child: ElevatedButton(
                onPressed: _isLoading ? null : _processPayment,
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.green,
                  foregroundColor: Colors.white,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(12),
                  ),
                ),
                child: _isLoading
                    ? const CircularProgressIndicator(color: Colors.white)
                    : Text(
                        _selectedMethod == 0
                            ? "Pay NGN ${widget.amount.toStringAsFixed(2)}"
                            : "I have made the transfer",
                        style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
              ),
            ),

            const SizedBox(height: 16),
            const Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(Icons.lock, size: 14, color: Colors.grey),
                SizedBox(width: 4),
                Text(
                  "Secured by Paystack",
                  style: TextStyle(color: Colors.grey, fontSize: 12),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildMethodTab(int index, String label, IconData icon) {
    final isSelected = _selectedMethod == index;
    return Expanded(
      child: GestureDetector(
        onTap: () => setState(() => _selectedMethod = index),
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 12),
          decoration: BoxDecoration(
            color: isSelected ? const Color(0xFF4A90E2) : Colors.white,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(
              color: isSelected ? const Color(0xFF4A90E2) : Colors.grey[300]!,
            ),
          ),
          child: Column(
            children: [
              Icon(icon, color: isSelected ? Colors.white : Colors.grey),
              const SizedBox(height: 4),
              Text(
                label,
                style: TextStyle(
                  color: isSelected ? Colors.white : Colors.grey,
                  fontWeight: FontWeight.bold,
                  fontSize: 12,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  InputDecoration _inputDecoration(String hint, IconData icon) {
    return InputDecoration(
      hintText: hint,
      prefixIcon: Icon(icon, color: Colors.grey),
      filled: true,
      fillColor: Colors.white,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: BorderSide.none,
      ),
    );
  }
}
