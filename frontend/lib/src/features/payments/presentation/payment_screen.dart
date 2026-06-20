import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:mediq_app/src/core/api/api_constants.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'package:mediq_app/src/core/constants/api_keys.dart';
import 'package:mediq_app/src/core/utils/ui_error_formatter.dart';
import 'package:mediq_app/src/features/appointments/presentation/schedule_screen.dart';
import 'package:mediq_app/src/features/auth/presentation/user_controller.dart';
import 'package:mediq_app/src/features/patient_dashboard/patient_home_screen.dart';
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

class _PaymentScreenState extends ConsumerState<PaymentScreen>
    with WidgetsBindingObserver {
  // ── State ────────────────────────────────────────────────────────────────────
  bool _isLoading = false;

  /// Set to true once the browser has been launched. The UI transitions to
  /// an "Awaiting confirmation" view so the user knows what to expect.
  bool _awaitingWebhook = false;
  bool _isVerifying = false;
  bool _hasOpenedCheckout = false;
  bool _hasAutoVerifiedForCurrentCheckout = false;
  String? _verificationMessage;
  String? _authorizationUrl;
  Timer? _verificationPollTimer;
  int _verificationPollAttempts = 0;

  /// The reference used for this checkout session (either pre-supplied by the
  /// backend or generated locally).
  late String _reference;

  // ── Fee calculation ──────────────────────────────────────────────────────────
  // Paystack adds its processing fees automatically at the checkout URL based
  // on our merchant settings. We only pass the base subscription/consult amount.
  double get _totalAmount => widget.baseAmount;

  // Paystack expects amounts in Kobo (smallest Naira unit). Multiply by 100.
  int get _totalAmountInKobo => (_totalAmount * 100).toInt();

  bool get _isAppointmentTransaction => const {
        'gp_consult',
        'specialist_consult',
        'vip_request',
      }.contains(widget.transactionType);

  String _formatCurrency(double amount) => '₦${amount.toStringAsFixed(2)}';

  // ── Lifecycle ────────────────────────────────────────────────────────────────
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    _verificationPollTimer?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed &&
        _hasOpenedCheckout &&
        _awaitingWebhook &&
        !_hasAutoVerifiedForCurrentCheckout &&
        !_isVerifying) {
      _hasAutoVerifiedForCurrentCheckout = true;
      _verifyPayment();
    }
  }

  // ── Checkout logic ───────────────────────────────────────────────────────────

  /// Calls the secure backend initialization endpoint and opens the returned
  /// Paystack `authorization_url` in the device browser.
  Future<void> _handlePayment() async {
    final userAsync = ref.read(userProvider);
    final user = userAsync.value;
    final authenticatedUserId = int.tryParse(user?.id ?? '');
    final userId = authenticatedUserId ?? widget.userId;

    if (user == null ||
        user.email.trim().isEmpty ||
        userId == null ||
        userId <= 0) {
      await _showAuthRequiredDialog();
      if (mounted) Navigator.of(context).maybePop();
      return;
    }

    if (_totalAmount <= 0) {
      _showSnack('This payment has an invalid amount.', isError: true);
      return;
    }

    final appointmentId = widget.appointmentId;
    final backendReference = widget.paystackReference?.trim();
    if (_isAppointmentTransaction &&
        (appointmentId == null ||
            appointmentId <= 0 ||
            backendReference == null ||
            backendReference.isEmpty)) {
      _showSnack(
        'This appointment is missing its secure payment reference. Refresh your appointments and try again.',
        isError: true,
      );
      return;
    }

    setState(() => _isLoading = true);

    final String dynamicReference = _isAppointmentTransaction
        ? backendReference!
        : widget.paystackReference ??
            'MDQ-${widget.transactionType}-${appointmentId ?? 0}-$userId-'
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
      final responseReference = response.data['reference']?.toString();

      if (authorizationUrl == null || authorizationUrl.isEmpty) {
        _showSnack(
          'Payment gateway returned an invalid URL. Please try again.',
          isError: true,
        );
        return;
      }

      // ── Step 2: Launch the checkout URL in the device browser ──────────────
      _reference = responseReference?.isNotEmpty == true
          ? responseReference!
          : dynamicReference;
      _authorizationUrl = authorizationUrl;
      final uri = Uri.parse(authorizationUrl);
      if (!await canLaunchUrl(uri)) {
        _showSnack(
          'Cannot open the payment page. Please check your browser settings.',
          isError: true,
        );
        return;
      }

      // ── Step 3: Transition UI to "Awaiting confirmation" state ────────────
      // The backend webhook may confirm the DB while the user is in Paystack.
      // When the app resumes, we also call /verify/{reference} to close the
      // loop immediately if the webhook is delayed.
      if (mounted) {
        setState(() {
          _awaitingWebhook = true;
          _hasOpenedCheckout = true;
          _hasAutoVerifiedForCurrentCheckout = false;
          _verificationMessage = 'Waiting for Paystack confirmation...';
        });
      }

      await launchUrl(uri, mode: LaunchMode.externalApplication);
      _startVerificationPolling();
    } on DioException catch (e) {
      final detail = e.response?.data is Map
          ? (e.response?.data as Map)['detail']?.toString() ?? ''
          : '';
      if (detail.toLowerCase().contains('already been paid')) {
        await _completePayment();
        return;
      }
      if (detail.toLowerCase().contains('duplicate transaction reference')) {
        if (mounted) {
          setState(() {
            _awaitingWebhook = true;
            _verificationMessage =
                'This checkout already exists. Checking its payment status...';
          });
          _startVerificationPolling();
          await _verifyPayment();
        }
        return;
      }
      _showSnack(UIErrorFormatter.getMessage(e), isError: true);
      debugPrint('[PAYMENTS] DioException during initialize: $e');
    } catch (e) {
      _showSnack(UIErrorFormatter.getMessage(e), isError: true);
      debugPrint('[PAYMENTS] Unexpected error during initialize: $e');
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  Future<void> _reopenPaymentPage() async {
    final authorizationUrl = _authorizationUrl;
    if (authorizationUrl == null || authorizationUrl.isEmpty) {
      _showSnack(
        'The payment page is no longer available. Please try again.',
        isError: true,
      );
      return;
    }

    final uri = Uri.parse(authorizationUrl);
    if (!await canLaunchUrl(uri) ||
        !await launchUrl(uri, mode: LaunchMode.externalApplication)) {
      _showSnack(
        'Cannot open the payment page. Please check your browser settings.',
        isError: true,
      );
      return;
    }
    _startVerificationPolling();
  }

  void _startVerificationPolling() {
    _verificationPollTimer?.cancel();
    _verificationPollAttempts = 0;
    _verificationPollTimer =
        Timer.periodic(const Duration(seconds: 3), (timer) async {
      if (!mounted || !_awaitingWebhook) {
        timer.cancel();
        return;
      }
      if (_verificationPollAttempts >= 40) {
        timer.cancel();
        if (mounted) {
          setState(() {
            _verificationMessage =
                'Payment is not confirmed yet. Use "Check payment status" after completing checkout.';
          });
        }
        return;
      }
      if (_isVerifying) return;
      _verificationPollAttempts += 1;
      await _verifyPayment(silent: true);
    });
  }

  Future<void> _completePayment() async {
    _verificationPollTimer?.cancel();
    ref.invalidate(userProvider);
    if (_isAppointmentTransaction) {
      ref.invalidate(myAppointmentsProvider);
      ref.read(homeTabIndexProvider.notifier).state = 1;
    }
    if (!mounted) return;

    _showSnack('Payment confirmed successfully.');
    if (_isAppointmentTransaction) {
      context.go('/patient_home');
    } else {
      Navigator.of(context).pop(_reference);
    }
  }

  Future<void> _verifyPayment({bool silent = false}) async {
    if (_isVerifying || !mounted) return;

    setState(() {
      _isVerifying = true;
      if (!silent) {
        _verificationMessage = 'Verifying your payment...';
      }
    });

    try {
      final dio = ref.read(dioProvider);
      final response = await dio.get(
        '${ApiConstants.baseUrl}/api/v1/payments/verify/$_reference',
        options: Options(
          receiveTimeout: const Duration(seconds: 20),
        ),
      );

      final data = response.data;
      final verified = data is Map && data['verified'] == true;

      if (verified) {
        await _completePayment();
        return;
      }

      if (mounted && !silent) {
        setState(() {
          _verificationMessage =
              'Payment is not confirmed yet. If you completed payment, this should update shortly.';
        });
      }
    } on DioException catch (e) {
      if (mounted && !silent) {
        setState(() {
          _verificationMessage = UIErrorFormatter.getMessage(e);
        });
      }
    } catch (e) {
      if (mounted && !silent) {
        setState(() {
          _verificationMessage = UIErrorFormatter.getMessage(e);
        });
      }
    } finally {
      if (mounted) setState(() => _isVerifying = false);
    }
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
          const SizedBox(height: 12),
          Text(
            'Your appointment is confirmed only after MDQ+ verifies the payment with Paystack.',
            textAlign: TextAlign.center,
            style: theme.textTheme.bodySmall?.copyWith(
              color: cs.onSurfaceVariant,
              height: 1.4,
            ),
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
              child: _isVerifying
                  ? Padding(
                      padding: const EdgeInsets.all(28),
                      child: CircularProgressIndicator(
                        strokeWidth: 3,
                        color: cs.primary,
                      ),
                    )
                  : Icon(
                      Icons.hourglass_top_rounded,
                      size: 48,
                      color: cs.primary,
                    ),
            ),
          ),
          const SizedBox(height: 32),

          // ── Heading ───────────────────────────────────────────────────────────
          Text(
            _isVerifying
                ? 'Verifying Payment'
                : 'Awaiting Payment Confirmation',
            textAlign: TextAlign.center,
            style: theme.textTheme.headlineSmall?.copyWith(
              fontWeight: FontWeight.bold,
              color: cs.onSurface,
            ),
          ),
          const SizedBox(height: 16),

          // ── Body copy ─────────────────────────────────────────────────────────
          Text(
            _verificationMessage ??
                'Complete your payment in the browser that just opened.\n\n'
                    'When you return to MDQ+, we will verify it automatically.',
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
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
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

          // ── Verification status action ────────────────────────────────────────
          SizedBox(
            height: 56,
            child: ElevatedButton(
              onPressed: _isVerifying ? null : _verifyPayment,
              style: ElevatedButton.styleFrom(
                backgroundColor: cs.primary,
                foregroundColor: cs.onPrimary,
                disabledBackgroundColor: cs.primary.withOpacity(0.5),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                ),
                elevation: 0,
              ),
              child: _isVerifying
                  ? const SizedBox(
                      width: 22,
                      height: 22,
                      child: CircularProgressIndicator(
                        strokeWidth: 2.5,
                        color: Colors.white,
                      ),
                    )
                  : const Text(
                      'Check payment status',
                      style: TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w600,
                        letterSpacing: 0.2,
                      ),
                    ),
            ),
          ),
          const SizedBox(height: 16),

          // ── Re-open browser link ──────────────────────────────────────────────
          TextButton(
            onPressed: _isLoading || _isVerifying ? null : _reopenPaymentPage,
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
