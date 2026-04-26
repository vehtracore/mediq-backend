import 'package:flutter/material.dart';
import 'package:flutter_paystack_plus/flutter_paystack_plus.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/core/constants/api_keys.dart';
import 'package:mediq_app/src/features/auth/presentation/user_controller.dart';

class PaymentScreen extends ConsumerStatefulWidget {
  final String transactionType;
  final double baseAmount;
  final String title;

  const PaymentScreen({
    super.key,
    required this.transactionType,
    required this.baseAmount,
    required this.title,
  });

  @override
  ConsumerState<PaymentScreen> createState() => _PaymentScreenState();
}

class _PaymentScreenState extends ConsumerState<PaymentScreen> {

  // ── Fee calculation ─────────────────────────────────────────────────────────
  double get _processingFee => (widget.baseAmount * 0.015) + 100.0;
  double get _totalAmount => widget.baseAmount + _processingFee;

  // Paystack expects amounts in Kobo (smallest Naira unit). Multiply by 100.
  int get _totalAmountInKobo => (_totalAmount * 100).toInt();

  String _formatCurrency(double amount) => '₦${amount.toStringAsFixed(2)}';

  // ── Checkout ────────────────────────────────────────────────────────────────
  Future<void> _handlePayment() async {
    // Get the signed-in user's email to attach to the charge.
    final user = ref.read(userProvider).value;
    final email = user?.email ?? 'customer@mediqplus.app';

    // Build a unique reference so we can reconcile on the backend.
    final reference = 'MDQ_${widget.transactionType}_${DateTime.now().millisecondsSinceEpoch}';

    // Show a non-blocking "Connecting…" snackbar while the sheet opens.
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
      content: Text('Connecting to secure gateway…'),
      behavior: SnackBarBehavior.floating,
      duration: Duration(seconds: 2),
    ));

    try {
      await FlutterPaystackPlus.openPaystackPopup(
        context: context,
        customerEmail: email,
        amount: _totalAmountInKobo.toString(), 
        reference: reference,
        secretKey: paystackSecretKey,
        callBackUrl: 'https://api.mdqplus.com', // Dummy URL to trigger WebView closure
        onSuccess: () {
          if (!mounted) return;
          ScaffoldMessenger.of(context).clearSnackBars();
          _showSnack('Payment Successful! Reference: $reference');
          Navigator.of(context).pop(reference);
        },
        onClosed: () {
          if (!mounted) return;
          ScaffoldMessenger.of(context).clearSnackBars();
          _showSnack('Payment was cancelled.', isError: true);
        },
      );
    } catch (e) {
      // Any exception from the SDK — surface the exact message so we can debug.
      if (!mounted) return;
      ScaffoldMessenger.of(context).clearSnackBars();
      _showSnack('Checkout error: ${e.toString()}', isError: true);
      debugPrint('[PAYSTACK] Checkout exception: $e');
    }
  }

  void _showSnack(String message, {bool isError = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(message),
      backgroundColor:
          isError ? const Color(0xFFE53935) : const Color(0xFF2E7D32),
      behavior: SnackBarBehavior.floating,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      margin: const EdgeInsets.fromLTRB(16, 0, 16, 16),
      duration: const Duration(seconds: 5),
    ));
  }

  // ── Build ───────────────────────────────────────────────────────────────────
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final cs = theme.colorScheme;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Checkout',
            style: TextStyle(fontWeight: FontWeight.w600)),
        centerTitle: true,
        elevation: 0,
        backgroundColor: Colors.transparent,
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // ── Order Summary Card ────────────────────────────────────────
              Card(
                elevation: 0,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(16),
                  side: BorderSide(color: cs.outlineVariant.withOpacity(0.5)),
                ),
                color: cs.surface,
                child: Padding(
                  padding: const EdgeInsets.all(24.0),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('ORDER SUMMARY',
                          style: theme.textTheme.labelMedium?.copyWith(
                            color: cs.onSurfaceVariant,
                            letterSpacing: 1.2,
                            fontWeight: FontWeight.w600,
                          )),
                      const SizedBox(height: 12),
                      Text(widget.title,
                          style: theme.textTheme.titleLarge?.copyWith(
                            fontWeight: FontWeight.w700,
                            color: cs.onSurface,
                          )),
                      const SizedBox(height: 32),
                      _PriceRow(
                        label: 'Subtotal',
                        amount: _formatCurrency(widget.baseAmount),
                        theme: theme,
                      ),
                      const SizedBox(height: 16),
                      _PriceRow(
                        label: 'Processing Fee (1.5% + ₦100)',
                        amount: _formatCurrency(_processingFee),
                        theme: theme,
                      ),
                      const Padding(
                        padding: EdgeInsets.symmetric(vertical: 20.0),
                        child: Divider(height: 1),
                      ),
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text('Total',
                              style: theme.textTheme.titleMedium?.copyWith(
                                fontWeight: FontWeight.bold,
                                color: cs.onSurface,
                              )),
                          Text(_formatCurrency(_totalAmount),
                              style: theme.textTheme.headlineSmall?.copyWith(
                                fontWeight: FontWeight.bold,
                                color: cs.primary,
                              )),
                        ],
                      ),
                    ],
                  ),
                ),
              ),

              const Spacer(),

              // ── Security badge ─────────────────────────────────────────────
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(Icons.lock_rounded,
                      size: 16, color: cs.onSurfaceVariant),
                  const SizedBox(width: 8),
                  Text('Secured by Paystack',
                      style: theme.textTheme.bodyMedium?.copyWith(
                        color: cs.onSurfaceVariant,
                        fontWeight: FontWeight.w500,
                      )),
                ],
              ),
              const SizedBox(height: 24),

              // ── Pay button ──────────────────────────────────────────────────
              SizedBox(
                height: 56,
                child: ElevatedButton(
                  onPressed: _handlePayment,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: cs.primary,
                    foregroundColor: cs.onPrimary,
                    disabledBackgroundColor: cs.primary.withOpacity(0.5),
                    shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12)),
                    elevation: 0,
                  ),
                  child: Text(
                    'Pay ${_formatCurrency(_totalAmount)}',
                    style: const TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.w600,
                        letterSpacing: 0.5),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// ─── Reusable price row ───────────────────────────────────────────────────────
class _PriceRow extends StatelessWidget {
  final String label;
  final String amount;
  final ThemeData theme;

  const _PriceRow({required this.label, required this.amount, required this.theme});

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Expanded(
          child: Text(label,
              style: theme.textTheme.bodyMedium
                  ?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
        ),
        Text(amount,
            style: theme.textTheme.bodyLarge?.copyWith(
                fontWeight: FontWeight.w600,
                color: theme.colorScheme.onSurface)),
      ],
    );
  }
}
