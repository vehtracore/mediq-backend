import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/core/api/api_constants.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'package:mediq_app/src/core/constants/api_keys.dart';
import 'package:mediq_app/src/features/auth/presentation/user_controller.dart';
import 'package:url_launcher/url_launcher.dart';

/// Payment screen — secure server-side checkout flow.
///
/// Architecture
/// ------------
/// 1. The screen calls  POST /api/v1/payments/initialize  on the MDQ+ backend.
/// 2. The backend proxies the request to Paystack using the Secret Key
///    (which never leaves the server).
/// 3. The backend returns an `authorization_url`.
/// 4. The frontend opens that URL in the device browser via url_launcher.
/// 5. After the user completes payment, Paystack fires a webhook to the backend
///    which confirms the appointment / subscription in the database.
/// 6. The frontend shows a "Awaiting confirmation" state and pops back to the
///    calling screen with the reference string so that screen can poll or
///    display a pending badge while the webhook arrives.
class PaymentScreen extends ConsumerStatefulWidget {
  final String transactionType;
  final double baseAmount;
  final String title;

  /// Optional IDs embedded in the reference so the backend webhook/watchdog
  /// can identify the correct DB row.
  final int? appointmentId;
  final int? userId;

  /// A pre-generated backend reference. When provided (e.g. from the
  /// appointments router), this exact string is used. Otherwise the screen
  /// generates one locally in the standard MDQ format.
  final String? paystackReference;

  const PaymentScreen({
    super.key,
    required this.transactionType,
    required this.baseAmount,
    required this.title,
    this.appointmentId,
    this.userId,
    this.paystackReference,
  });

  @override
  ConsumerState<PaymentScreen> createState() => _PaymentScreenState();
}

class _PaymentScreenState extends ConsumerState<PaymentScreen> {
  // ── State ────────────────────────────────────────────────────────────────────
  bool _isLoading = false;

  /// Set to true once the browser has been launched. The UI transitions to
  /// an "Awaiting confirmation" view so the user knows what to expect.
  bool _awaitingWebhook = false;

  /// The reference used for this checkout session (either pre-supplied by the
  /// backend or generated locally).
  late String _reference;

  // ── Fee calculation ──────────────────────────────────────────────────────────
  // Paystack adds its processing fees automatically at the checkout URL based
  // on our merchant settings. We only pass the base subscription/consult amount.
  double get _totalAmount => widget.baseAmount;

  // Paystack expects amounts in Kobo (smallest Naira unit). Multiply by 100.
  int get _totalAmountInKobo => (_totalAmount * 100).toInt();

  String _formatCurrency(double amount) => '₦${amount.toStringAsFixed(2)}';

  // ── Lifecycle ────────────────────────────────────────────────────────────────
  @override
  void initState() {
    super.initState();
  }

  // ── Checkout logic ───────────────────────────────────────────────────────────

  /// Calls the secure backend initialization endpoint and opens the returned
  /// Paystack `authorization_url` in the device browser.
  Future<void> _handlePayment() async {
    final userAsync = ref.read(userProvider);
    final user = userAsync.value;
    final userId = widget.userId;

    if (user == null || user.email.trim().isEmpty || userId == null || userId <= 0) {
      await _showAuthRequiredDialog();
      if (mounted) Navigator.of(context).maybePop();
      return;
    }

    setState(() => _isLoading = true);

    final appointmentId = widget.appointmentId ?? 0;
    final String dynamicReference = widget.paystackReference ??
        'MDQ-${widget.transactionType}-$appointmentId-$userId-'
            '${DateTime.now().millisecondsSinceEpoch}';
    
    // Cache it in state so the awaiting confirmation view and back navigation can use it.
    _reference = dynamicReference;

    try {
      // ── Step 1: Call the backend to initialize the transaction ─────────────
      final dio = ref.read(dioProvider);
      final planCode = _planCodeForType(widget.transactionType);

      final response = await dio.post(
        '${ApiConstants.baseUrl}/api/v1/payments/initialize',
        data: {
          'email': user.email.trim(),
          'amount': _totalAmountInKobo,
          'reference': dynamicReference,
          // Only included for subscription types; null is omitted by Dio
          if (planCode != null) 'plan': planCode,
        },
        options: Options(
          contentType: 'application/json',
          receiveTimeout: const Duration(seconds: 20),
        ),
      );

      final authorizationUrl = response.data['authorization_url'] as String?;

      if (authorizationUrl == null || authorizationUrl.isEmpty) {
        _showSnack(
          'Payment gateway returned an invalid URL. Please try again.',
          isError: true,
        );
        return;
      }

      // ── Step 2: Launch the checkout URL in the device browser ──────────────
      final uri = Uri.parse(authorizationUrl);
      if (!await canLaunchUrl(uri)) {
        _showSnack(
          'Cannot open the payment page. Please check your browser settings.',
          isError: true,
        );
        return;
      }

      await launchUrl(uri, mode: LaunchMode.externalApplication);

      // ── Step 3: Transition UI to "Awaiting confirmation" state ────────────
      // The actual DB update is handled by the backend webhook. The frontend
      // pops back with the reference so the calling screen can display a
      // "Payment pending" badge or poll the status.
      if (mounted) {
        setState(() => _awaitingWebhook = true);
      }
    } on DioException catch (e) {
      final serverMsg = e.response?.data is Map
          ? e.response?.data['detail'] ?? e.message
          : e.message;
      _showSnack('Payment error: $serverMsg', isError: true);
      debugPrint('[PAYMENTS] DioException during initialize: $e');
    } catch (e) {
      _showSnack('Unexpected error: ${e.toString()}', isError: true);
      debugPrint('[PAYMENTS] Unexpected error during initialize: $e');
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  /// Called when the user taps "Done" after the browser has been opened.
  /// Returns the reference to the previous screen so it can display a
  /// pending-payment indicator or trigger a status poll.
  void _dismissToCallerWithReference() {
    Navigator.of(context).pop(_reference);
  }

  /// Returns the Paystack Plan Code for recurring subscription types,
  /// or null for one-time consultation payments.
  ///
  /// The plan code is forwarded to the backend /initialize endpoint so
  /// Paystack creates a recurring charge instead of a one-time transaction.
  String? _planCodeForType(String transactionType) {
    switch (transactionType) {
      case 'subscription':
        return individualPlanCode;
      case 'family_subscription':
        return familyPlanCode;
      default:
        // GP / specialist consultations are one-time charges — no plan code.
        return null;
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
      duration: const Duration(seconds: 6),
    ));
  }

  Future<void> _showAuthRequiredDialog() async {
    if (!mounted) return;

    await showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Session Required'),
        content: const Text(
          'We could not verify your secure session. Please sign in again before starting payment.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('OK'),
          ),
        ],
      ),
    );
  }

  // ── Build ────────────────────────────────────────────────────────────────────
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final cs = theme.colorScheme;

    return Scaffold(
      appBar: AppBar(
        title: const Text(
          'Checkout',
          style: TextStyle(fontWeight: FontWeight.w600),
        ),
        centerTitle: true,
        elevation: 0,
        backgroundColor: Colors.transparent,
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24.0),
          child: _awaitingWebhook
              ? _buildAwaitingConfirmationView(theme, cs)
              : _buildSummaryView(theme, cs),
        ),
      ),
    );
  }

  // ── Summary view (before checkout is opened) ─────────────────────────────────
  Widget _buildSummaryView(ThemeData theme, ColorScheme cs) {
    return SingleChildScrollView(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
        // ── Order Summary Card ────────────────────────────────────────────────
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
                Text(
                  'ORDER SUMMARY',
                  style: theme.textTheme.labelMedium?.copyWith(
                    color: cs.onSurfaceVariant,
                    letterSpacing: 1.2,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 12),
                Text(
                  widget.title,
                  style: theme.textTheme.titleLarge?.copyWith(
                    fontWeight: FontWeight.w700,
                    color: cs.onSurface,
                  ),
                ),
                const SizedBox(height: 32),
                _PriceRow(
                  label: 'Base Amount',
                  amount: _formatCurrency(widget.baseAmount),
                  theme: theme,
                ),
                const SizedBox(height: 16),
                _PriceRow(
                  label: 'Processing Fee',
                  amount: 'Calculated at checkout',
                  theme: theme,
                ),
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 20.0),
                  child: Divider(height: 1),
                ),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(
                      'Total',
                      style: theme.textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.bold,
                        color: cs.onSurface,
                      ),
                    ),
                    Text(
                      _formatCurrency(_totalAmount),
                      style: theme.textTheme.headlineSmall?.copyWith(
                        fontWeight: FontWeight.bold,
                        color: cs.primary,
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),

        const SizedBox(height: 48),

        // ── Security badge ────────────────────────────────────────────────────
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.lock_rounded, size: 16, color: cs.onSurfaceVariant),
            const SizedBox(width: 8),
            Text(
              'Secured by Paystack',
              style: theme.textTheme.bodyMedium?.copyWith(
                color: cs.onSurfaceVariant,
                fontWeight: FontWeight.w500,
              ),
            ),
          ],
        ),
        const SizedBox(height: 24),

        // ── Pay button ────────────────────────────────────────────────────────
        SizedBox(
          height: 56,
          child: ElevatedButton(
            onPressed: _isLoading ? null : _handlePayment,
            style: ElevatedButton.styleFrom(
              backgroundColor: cs.primary,
              foregroundColor: cs.onPrimary,
              disabledBackgroundColor: cs.primary.withOpacity(0.5),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(12),
              ),
              elevation: 0,
            ),
            child: _isLoading
                ? const SizedBox(
                    width: 24,
                    height: 24,
                    child: CircularProgressIndicator(
                      strokeWidth: 2.5,
                      color: Colors.white,
                    ),
                  )
                : Text(
                    'Pay ${_formatCurrency(_totalAmount)}',
                    style: const TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.w600,
                      letterSpacing: 0.5,
                    ),
                  ),
          ),
        ),
        ],
      ),
    );
  }

  // ── Awaiting webhook confirmation view ───────────────────────────────────────
  Widget _buildAwaitingConfirmationView(ThemeData theme, ColorScheme cs) {
    return SingleChildScrollView(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
        // ── Animated icon ─────────────────────────────────────────────────────
        Center(
          child: Container(
            width: 96,
            height: 96,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: cs.primaryContainer,
            ),
            child: Icon(
              Icons.hourglass_top_rounded,
              size: 48,
              color: cs.primary,
            ),
          ),
        ),
        const SizedBox(height: 32),

        // ── Heading ───────────────────────────────────────────────────────────
        Text(
          'Awaiting Payment Confirmation',
          textAlign: TextAlign.center,
          style: theme.textTheme.headlineSmall?.copyWith(
            fontWeight: FontWeight.bold,
            color: cs.onSurface,
          ),
        ),
        const SizedBox(height: 16),

        // ── Body copy ─────────────────────────────────────────────────────────
        Text(
          'Complete your payment in the browser that just opened.\n\n'
          'Once Paystack processes your payment, your appointment will be '
          'confirmed automatically — no further action is needed here.',
          textAlign: TextAlign.center,
          style: theme.textTheme.bodyMedium?.copyWith(
            color: cs.onSurfaceVariant,
            height: 1.6,
          ),
        ),
        const SizedBox(height: 12),

        // ── Reference chip ────────────────────────────────────────────────────
        Center(
          child: Container(
            padding:
                const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            decoration: BoxDecoration(
              color: cs.surfaceContainerHighest,
              borderRadius: BorderRadius.circular(8),
            ),
            child: Text(
              'Ref: $_reference',
              style: theme.textTheme.labelSmall?.copyWith(
                color: cs.onSurfaceVariant,
                fontFamily: 'monospace',
              ),
            ),
          ),
        ),
        const SizedBox(height: 48),

        // ── Done button ───────────────────────────────────────────────────────
        SizedBox(
          height: 56,
          child: ElevatedButton(
            onPressed: _dismissToCallerWithReference,
            style: ElevatedButton.styleFrom(
              backgroundColor: cs.primary,
              foregroundColor: cs.onPrimary,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(12),
              ),
              elevation: 0,
            ),
            child: const Text(
              'Done',
              style: TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.w600,
                letterSpacing: 0.5,
              ),
            ),
          ),
        ),
        const SizedBox(height: 16),

        // ── Re-open browser link ──────────────────────────────────────────────
        TextButton(
          onPressed: _handlePayment,
          child: Text(
            'Re-open payment page',
            style: TextStyle(color: cs.primary),
          ),
        ),
        ],
      ),
    );
  }
}

// ─── Reusable price row ───────────────────────────────────────────────────────
class _PriceRow extends StatelessWidget {
  final String label;
  final String amount;
  final ThemeData theme;

  const _PriceRow({
    required this.label,
    required this.amount,
    required this.theme,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Expanded(
          child: Text(
            label,
            style: theme.textTheme.bodyMedium
                ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
          ),
        ),
        Text(
          amount,
          style: theme.textTheme.bodyLarge?.copyWith(
            fontWeight: FontWeight.w600,
            color: theme.colorScheme.onSurface,
          ),
        ),
      ],
    );
  }
}
