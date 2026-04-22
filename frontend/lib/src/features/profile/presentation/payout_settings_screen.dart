import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:mediq_app/src/features/doctors/data/doctor_repository.dart';

class PayoutSettingsScreen extends ConsumerStatefulWidget {
  const PayoutSettingsScreen({super.key});

  @override
  ConsumerState<PayoutSettingsScreen> createState() =>
      _PayoutSettingsScreenState();
}

// ─── Nigerian bank catalogue ────────────────────────────────────────────────
class _NigerianBank {
  final String name;
  final String code;
  const _NigerianBank(this.name, this.code);
}

const _kBanks = [
  _NigerianBank('Access Bank', '044'),
  _NigerianBank('GTBank', '058'),
  _NigerianBank('UBA', '033'),
  _NigerianBank('First Bank', '011'),
  _NigerianBank('Zenith Bank', '057'),
  _NigerianBank('Kuda Bank', '50211'),
  _NigerianBank('Opay', '999992'),
];

// ─── State ───────────────────────────────────────────────────────────────────
class _PayoutSettingsScreenState
    extends ConsumerState<PayoutSettingsScreen> {
  final _formKey = GlobalKey<FormState>();
  final _accountController = TextEditingController();

  _NigerianBank? _selectedBank;
  bool _isLoading = false;

  @override
  void dispose() {
    _accountController.dispose();
    super.dispose();
  }

  // ── Submit handler ─────────────────────────────────────────────────────────
  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    if (_selectedBank == null) {
      _showSnack('Please select a bank.', isError: true);
      return;
    }

    setState(() => _isLoading = true);

    try {
      await ref.read(doctorRepositoryProvider).updatePayoutSettings(
            bankCode: _selectedBank!.code,
            accountNumber: _accountController.text.trim(),
          );

      if (!mounted) return;
      _showSnack('Payout account linked securely ✅');
      context.pop();
    } on DioException catch (e) {
      // Surface Paystack's own error message when available
      final detail = e.response?.data?['detail'] as String?;
      _showSnack(detail ?? 'Failed to link account. Check your details.',
          isError: true);
    } catch (_) {
      _showSnack('An unexpected error occurred. Please try again.',
          isError: true);
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  void _showSnack(String message, {bool isError = false}) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: isError ? const Color(0xFFE53935) : const Color(0xFF2E7D32),
        behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
        margin: const EdgeInsets.fromLTRB(16, 0, 16, 16),
      ),
    );
  }

  // ── Build ──────────────────────────────────────────────────────────────────
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;

    // Design tokens
    const accent = Color(0xFF4A90E2);
    final cardColor = isDark ? const Color(0xFF1E2A3A) : Colors.white;
    final subtleText = isDark ? Colors.white54 : Colors.grey[600];

    return Scaffold(
      backgroundColor: theme.scaffoldBackgroundColor,
      appBar: AppBar(
        backgroundColor: theme.appBarTheme.backgroundColor,
        elevation: 0,
        leading: IconButton(
          icon: Icon(Icons.arrow_back, color: theme.iconTheme.color),
          onPressed: () => context.pop(),
        ),
        title: Text('Payout Settings', style: theme.textTheme.titleLarge),
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(20),
          child: Form(
            key: _formKey,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // ── Info card ────────────────────────────────────────────
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    gradient: const LinearGradient(
                      colors: [Color(0xFF4A90E2), Color(0xFF1565C0)],
                      begin: Alignment.topLeft,
                      end: Alignment.bottomRight,
                    ),
                    borderRadius: BorderRadius.circular(16),
                    boxShadow: [
                      BoxShadow(
                        color: accent.withOpacity(0.3),
                        blurRadius: 16,
                        offset: const Offset(0, 6),
                      ),
                    ],
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Icon(Icons.account_balance_wallet_rounded,
                          color: Colors.white, size: 32),
                      const SizedBox(height: 12),
                      const Text(
                        'Link Your Bank Account',
                        style: TextStyle(
                          color: Colors.white,
                          fontSize: 18,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      const SizedBox(height: 6),
                      Text(
                        'We use Paystack to securely route 70% of every\nconsultation fee directly to your account.',
                        style: TextStyle(
                          color: Colors.white.withOpacity(0.85),
                          fontSize: 13,
                          height: 1.5,
                        ),
                      ),
                    ],
                  ),
                ),

                const SizedBox(height: 32),

                // ── Bank dropdown ─────────────────────────────────────────
                Text(
                  'Bank',
                  style: theme.textTheme.bodyMedium?.copyWith(
                    fontWeight: FontWeight.w600,
                    color: subtleText,
                  ),
                ),
                const SizedBox(height: 8),
                Container(
                  decoration: BoxDecoration(
                    color: cardColor,
                    borderRadius: BorderRadius.circular(14),
                    boxShadow: isDark
                        ? []
                        : [
                            BoxShadow(
                              color: Colors.grey.withOpacity(0.08),
                              blurRadius: 8,
                              offset: const Offset(0, 3),
                            ),
                          ],
                  ),
                  child: DropdownButtonFormField<_NigerianBank>(
                    value: _selectedBank,
                    isExpanded: true,
                    decoration: InputDecoration(
                      prefixIcon: const Icon(Icons.account_balance_rounded,
                          color: accent),
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(14),
                        borderSide: BorderSide.none,
                      ),
                      filled: true,
                      fillColor: Colors.transparent,
                      hintText: 'Select your bank',
                      hintStyle: TextStyle(color: subtleText),
                    ),
                    dropdownColor: cardColor,
                    items: _kBanks
                        .map(
                          (bank) => DropdownMenuItem(
                            value: bank,
                            child: Text(bank.name,
                                style: theme.textTheme.bodyLarge),
                          ),
                        )
                        .toList(),
                    onChanged: _isLoading
                        ? null
                        : (val) => setState(() => _selectedBank = val),
                    validator: (_) =>
                        _selectedBank == null ? 'Please select a bank' : null,
                  ),
                ),

                const SizedBox(height: 20),

                // ── Account number field ─────────────────────────────────
                Text(
                  'Account Number',
                  style: theme.textTheme.bodyMedium?.copyWith(
                    fontWeight: FontWeight.w600,
                    color: subtleText,
                  ),
                ),
                const SizedBox(height: 8),
                Container(
                  decoration: BoxDecoration(
                    color: cardColor,
                    borderRadius: BorderRadius.circular(14),
                    boxShadow: isDark
                        ? []
                        : [
                            BoxShadow(
                              color: Colors.grey.withOpacity(0.08),
                              blurRadius: 8,
                              offset: const Offset(0, 3),
                            ),
                          ],
                  ),
                  child: TextFormField(
                    controller: _accountController,
                    enabled: !_isLoading,
                    keyboardType: TextInputType.number,
                    maxLength: 10,
                    style: theme.textTheme.bodyLarge,
                    decoration: InputDecoration(
                      prefixIcon: const Icon(Icons.dialpad_rounded, color: accent),
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(14),
                        borderSide: BorderSide.none,
                      ),
                      filled: true,
                      fillColor: Colors.transparent,
                      hintText: '10-digit NUBAN',
                      hintStyle: TextStyle(color: subtleText),
                      counterText: '', // hides the default maxLength counter
                    ),
                    validator: (val) {
                      if (val == null || val.trim().isEmpty) {
                        return 'Account number is required';
                      }
                      if (val.trim().length != 10 ||
                          !RegExp(r'^\d{10}$').hasMatch(val.trim())) {
                        return 'Must be exactly 10 digits';
                      }
                      return null;
                    },
                  ),
                ),

                const SizedBox(height: 40),

                // ── Submit button ─────────────────────────────────────────
                SizedBox(
                  width: double.infinity,
                  height: 54,
                  child: ElevatedButton(
                    onPressed: _isLoading ? null : _submit,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: accent,
                      disabledBackgroundColor: accent.withOpacity(0.5),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(14),
                      ),
                      elevation: _isLoading ? 0 : 4,
                    ),
                    child: _isLoading
                        ? const SizedBox(
                            width: 22,
                            height: 22,
                            child: CircularProgressIndicator(
                              strokeWidth: 2.5,
                              valueColor:
                                  AlwaysStoppedAnimation<Color>(Colors.white),
                            ),
                          )
                        : const Text(
                            'Link Payout Account',
                            style: TextStyle(
                              color: Colors.white,
                              fontSize: 16,
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                  ),
                ),

                const SizedBox(height: 16),

                // ── Security note ─────────────────────────────────────────
                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Icon(Icons.lock_outline, size: 13, color: subtleText),
                    const SizedBox(width: 4),
                    Text(
                      'Secured by Paystack — we never store raw account data',
                      style: TextStyle(fontSize: 11, color: subtleText),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
