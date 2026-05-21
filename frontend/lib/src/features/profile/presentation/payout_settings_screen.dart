import 'package:dio/dio.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:mediq_app/src/features/auth/data/auth_repository.dart';
import 'package:mediq_app/src/features/doctors/data/doctor_repository.dart';
import 'package:mediq_app/src/shared/presentation/widgets/skeleton_loader.dart';
import '../../../../presentation/widgets/global_error_widget.dart';

// ─── Bank model ───────────────────────────────────────────────────────────────
class _PaystackBank {
  final String name;
  final String code;
  const _PaystackBank(this.name, this.code);
}

// ─── Doctor profile provider (reuses existing auth repo) ─────────────────────
final _myDoctorProvider = FutureProvider.autoDispose((ref) async {
  return await ref.watch(authRepositoryProvider).getMyDoctorProfile();
});

// ─── Screen ───────────────────────────────────────────────────────────────────
class PayoutSettingsScreen extends ConsumerStatefulWidget {
  const PayoutSettingsScreen({super.key});
  @override
  ConsumerState<PayoutSettingsScreen> createState() => _PayoutSettingsScreenState();
}

class _PayoutSettingsScreenState extends ConsumerState<PayoutSettingsScreen> {
  final _formKey = GlobalKey<FormState>();
  final _accountController = TextEditingController();

  List<_PaystackBank> _banks = [];
  bool _banksLoading = true;
  String? _banksError;

  _PaystackBank? _selectedBank;
  bool _isLoading = false;

  // When true, hides the linked-account card and shows the form to override
  bool _overrideMode = false;

  @override
  void initState() {
    super.initState();
    _fetchBanks();
  }

  @override
  void dispose() {
    _accountController.dispose();
    super.dispose();
  }

  Future<void> _fetchBanks() async {
    setState(() { _banksLoading = true; _banksError = null; });
    try {
      final dio = Dio();
      final response = await dio.get(
        'https://api.paystack.co/bank',
        queryParameters: {'country': 'nigeria', 'perPage': 100},
        options: Options(sendTimeout: const Duration(seconds: 10), receiveTimeout: const Duration(seconds: 10)),
      );
      final rawList = response.data['data'] as List<dynamic>;
      final banks = rawList
          .map((b) => _PaystackBank(b['name'] as String, b['code'] as String))
          .toList()
        ..sort((a, b) => a.name.compareTo(b.name));
      if (mounted) setState(() { _banks = banks; _banksLoading = false; });
    } on DioException catch (e) {
      if (mounted) {
        setState(() {
        _banksError = e.response?.data?['message'] as String? ?? 'Could not load banks.';
        _banksLoading = false;
      });
      }
    } catch (_) {
      if (mounted) setState(() { _banksError = 'Unexpected error loading banks.'; _banksLoading = false; });
    }
  }

  void _openBankPicker() {
    if (_banksLoading || _banksError != null || _isLoading) return;
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (sheetCtx) => _BankPickerSheet(
        banks: _banks,
        selectedBank: _selectedBank,
        onSelect: (bank) { setState(() => _selectedBank = bank); Navigator.pop(sheetCtx); },
      ),
    );
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    if (_selectedBank == null) { _showSnack('Please select a bank.', isError: true); return; }
    setState(() => _isLoading = true);
    try {
      await ref.read(doctorRepositoryProvider).updatePayoutSettings(
        bankCode: _selectedBank!.code,
        accountNumber: _accountController.text.trim(),
      );
      if (!mounted) return;
      // Invalidate so the linked-account card refreshes
      ref.invalidate(_myDoctorProvider);
      _showSnack('Payout account linked securely ✅');
      setState(() => _overrideMode = false);
    } on DioException catch (e) {
      final detail = e.response?.data?['detail'] as String?;
      _showSnack(detail ?? 'Failed to link account. Check your details.', isError: true);
    } catch (_) {
      _showSnack('An unexpected error occurred. Please try again.', isError: true);
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  void _showSnack(String msg, {bool isError = false}) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(msg),
      backgroundColor: isError ? const Color(0xFFE53935) : const Color(0xFF2E7D32),
      behavior: SnackBarBehavior.floating,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      margin: const EdgeInsets.fromLTRB(16, 0, 16, 16),
    ));
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;
    const accent = Color(0xFF4A90E2);
    final subtleText = isDark ? Colors.white54 : Colors.grey[600];

    final doctorAsync = ref.watch(_myDoctorProvider);

    return Scaffold(
      backgroundColor: theme.scaffoldBackgroundColor,
      appBar: AppBar(
        backgroundColor: theme.appBarTheme.backgroundColor,
        elevation: 0,
        leading: IconButton(icon: Icon(Icons.arrow_back, color: theme.iconTheme.color), onPressed: () => context.pop()),
        title: Text('Payout Settings', style: theme.textTheme.titleLarge),
      ),
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: () async => ref.invalidate(_myDoctorProvider),
          child: doctorAsync.when(
            loading: () => ListView.builder(
              physics: const AlwaysScrollableScrollPhysics(),
              itemCount: 4,
              padding: const EdgeInsets.all(20),
              itemBuilder: (context, index) => Padding(
                padding: const EdgeInsets.only(bottom: 16),
                child: SkeletonLoader(child: Container(height: 80, width: double.infinity, decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(16)))),
              ),
            ),
            error: (e, _) => ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              children: [
                SizedBox(
                  height: MediaQuery.of(context).size.height * 0.7,
                  child: GlobalErrorWidget(
                    error: e,
                    onRetry: () => ref.invalidate(_myDoctorProvider),
                  ),
                ),
              ],
            ),
            data: (doctor) {
              // ── Linked account view ───────────────────────────────────────────
              final isLinked = doctor.accountNumber != null && !_overrideMode;
              if (isLinked) {
                return SingleChildScrollView(
                  physics: const AlwaysScrollableScrollPhysics(),
                  child: _LinkedAccountView(
                    doctor: doctor,
                    onChangePressed: () => setState(() => _overrideMode = true),
                  ),
                );
              }
  
              // ── Setup / override form ─────────────────────────────────────────
              final cardColor = isDark ? const Color(0xFF1E2A3A) : Colors.white;
              return SingleChildScrollView(
                physics: const AlwaysScrollableScrollPhysics(),
                padding: const EdgeInsets.all(20),
                child: Form(
                key: _formKey,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // Info card
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(16),
                      decoration: BoxDecoration(
                        gradient: const LinearGradient(
                          colors: [Color(0xFF4A90E2), Color(0xFF1565C0)],
                          begin: Alignment.topLeft, end: Alignment.bottomRight,
                        ),
                        borderRadius: BorderRadius.circular(16),
                        boxShadow: [BoxShadow(color: accent.withOpacity(0.3), blurRadius: 16, offset: const Offset(0, 6))],
                      ),
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        const Icon(Icons.account_balance_wallet_rounded, color: Colors.white, size: 32),
                        const SizedBox(height: 12),
                        const Text('Link Your Bank Account', style: TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.bold)),
                        const SizedBox(height: 6),
                        Text('Connect your bank account to receive your consultation payouts.',
                            style: TextStyle(color: Colors.white.withOpacity(0.85), fontSize: 13, height: 1.5)),
                        const SizedBox(height: 10),
                        RichText(text: TextSpan(
                          text: 'Read our ',
                          style: TextStyle(color: Colors.white.withOpacity(0.7), fontSize: 12),
                          children: [TextSpan(
                            text: 'Payout Terms & Conditions',
                            style: const TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.bold,
                                decoration: TextDecoration.underline, decorationColor: Colors.white),
                            recognizer: TapGestureRecognizer()..onTap = () => _showSnack('Payout T&Cs coming soon.'),
                          )],
                        )),
                      ]),
                    ),

                    const SizedBox(height: 32),

                    // Bank label
                    Text('Bank', style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600, color: subtleText)),
                    const SizedBox(height: 8),

                    // Bank selector states
                    if (_banksLoading)
                      _stateContainer(cardColor, child: Row(children: [
                        const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: accent)),
                        const SizedBox(width: 12),
                        Text('Loading banks…', style: TextStyle(color: subtleText)),
                      ]))
                    else if (_banksError != null)
                      _stateContainer(cardColor, child: Row(children: [
                        const Icon(Icons.error_outline, color: Color(0xFFE53935), size: 18),
                        const SizedBox(width: 8),
                        Expanded(child: Text(_banksError!, style: const TextStyle(color: Color(0xFFE53935), fontSize: 13))),
                        TextButton(onPressed: _fetchBanks, child: const Text('Retry', style: TextStyle(color: accent))),
                      ]))
                    else
                      GestureDetector(
                        onTap: _isLoading ? null : _openBankPicker,
                        child: _stateContainer(cardColor,
                          shadow: isDark ? [] : [BoxShadow(color: Colors.grey.withOpacity(0.08), blurRadius: 8, offset: const Offset(0, 3))],
                          child: Row(children: [
                            const Icon(Icons.account_balance_rounded, color: accent, size: 20),
                            const SizedBox(width: 12),
                            Expanded(child: Text(
                              _selectedBank?.name ?? 'Select your bank',
                              style: theme.textTheme.bodyLarge?.copyWith(
                                  color: _selectedBank == null ? subtleText : theme.textTheme.bodyLarge?.color),
                            )),
                            Icon(Icons.expand_more_rounded, color: subtleText, size: 20),
                          ]),
                        ),
                      ),

                    const SizedBox(height: 20),

                    // Account number
                    Text('Account Number', style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600, color: subtleText)),
                    const SizedBox(height: 8),
                    Container(
                      decoration: BoxDecoration(
                        color: cardColor, borderRadius: BorderRadius.circular(14),
                        boxShadow: isDark ? [] : [BoxShadow(color: Colors.grey.withOpacity(0.08), blurRadius: 8, offset: const Offset(0, 3))],
                      ),
                      child: TextFormField(
                        controller: _accountController,
                        enabled: !_isLoading,
                        keyboardType: TextInputType.number,
                        maxLength: 10,
                        style: theme.textTheme.bodyLarge,
                        decoration: InputDecoration(
                          prefixIcon: const Icon(Icons.dialpad_rounded, color: accent),
                          border: OutlineInputBorder(borderRadius: BorderRadius.circular(14), borderSide: BorderSide.none),
                          filled: true, fillColor: Colors.transparent,
                          hintText: '10-digit account number',
                          hintStyle: TextStyle(color: subtleText),
                          counterText: '',
                        ),
                        validator: (val) {
                          if (val == null || val.trim().isEmpty) return 'Account number is required';
                          if (!RegExp(r'^\d{10}$').hasMatch(val.trim())) return 'Must be exactly 10 digits';
                          return null;
                        },
                      ),
                    ),

                    const SizedBox(height: 40),

                    // Submit button
                    SizedBox(
                      width: double.infinity, height: 54,
                      child: ElevatedButton(
                        onPressed: (_isLoading || _banksLoading || _banksError != null) ? null : _submit,
                        style: ElevatedButton.styleFrom(
                          backgroundColor: accent,
                          disabledBackgroundColor: accent.withOpacity(0.5),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                          elevation: _isLoading ? 0 : 4,
                        ),
                        child: _isLoading
                            ? const SizedBox(width: 22, height: 22,
                                child: CircularProgressIndicator(strokeWidth: 2.5, valueColor: AlwaysStoppedAnimation<Color>(Colors.white)))
                            : const Text('Link Payout Account',
                                style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
                      ),
                    ),

                    const SizedBox(height: 16),

                    // Security note
                    Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                      Icon(Icons.lock_outline, size: 13, color: subtleText),
                      const SizedBox(width: 4),
                      Text('Secured by Paystack — we never store raw account data',
                          style: TextStyle(fontSize: 11, color: subtleText)),
                    ]),
                  ],
                ),
              ),
            );
          },
        ),
        ),
      ),
    );
  }

  Widget _stateContainer(Color color, {required Widget child, List<BoxShadow>? shadow}) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
      decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(14), boxShadow: shadow ?? []),
      child: child,
    );
  }
}

// ─── Linked Account View ──────────────────────────────────────────────────────
class _LinkedAccountView extends StatelessWidget {
  final dynamic doctor;
  final VoidCallback onChangePressed;

  const _LinkedAccountView({required this.doctor, required this.onChangePressed});

  String _mask(String acct) {
    if (acct.length < 4) return acct;
    final last4 = acct.substring(acct.length - 4);
    return '•••• •••• $last4';
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;
    const accent = Color(0xFF4A90E2);
    final cardColor = isDark ? const Color(0xFF1E2A3A) : Colors.white;
    final subtleText = isDark ? Colors.white54 : Colors.grey[600];

    return Padding(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Success banner
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              gradient: const LinearGradient(
                colors: [Color(0xFF2E7D32), Color(0xFF1B5E20)],
                begin: Alignment.topLeft, end: Alignment.bottomRight,
              ),
              borderRadius: BorderRadius.circular(16),
              boxShadow: [BoxShadow(color: Colors.green.withOpacity(0.25), blurRadius: 16, offset: const Offset(0, 6))],
            ),
            child: const Row(children: [
              Icon(Icons.verified_rounded, color: Colors.white, size: 36),
              SizedBox(width: 14),
              Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('Account Linked', style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
                SizedBox(height: 4),
                Text('Your payouts are set up and ready.', style: TextStyle(color: Colors.white70, fontSize: 13)),
              ])),
            ]),
          ),

          const SizedBox(height: 28),

          Text('Linked Account', style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600, color: subtleText)),
          const SizedBox(height: 10),

          // Account detail card
          Container(
            padding: const EdgeInsets.all(20),
            decoration: BoxDecoration(
              color: cardColor, borderRadius: BorderRadius.circular(16),
              boxShadow: isDark ? [] : [BoxShadow(color: Colors.grey.withOpacity(0.08), blurRadius: 12, offset: const Offset(0, 4))],
            ),
            child: Row(children: [
              Container(
                width: 48, height: 48,
                decoration: BoxDecoration(color: accent.withOpacity(0.12), borderRadius: BorderRadius.circular(12)),
                child: const Icon(Icons.account_balance_rounded, color: accent, size: 24),
              ),
              const SizedBox(width: 16),
              Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(
                  'Bank Code: ${doctor.bankCode ?? '—'}',
                  style: theme.textTheme.bodySmall?.copyWith(color: subtleText),
                ),
                const SizedBox(height: 4),
                Text(
                  _mask(doctor.accountNumber ?? ''),
                  style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold, letterSpacing: 1.2),
                ),
              ])),
              const Icon(Icons.check_circle_rounded, color: Color(0xFF2E7D32), size: 22),
            ]),
          ),

          const SizedBox(height: 24),

          // Change account button
          SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              onPressed: onChangePressed,
              icon: const Icon(Icons.edit_outlined, size: 18),
              label: const Text('Change Account'),
              style: OutlinedButton.styleFrom(
                foregroundColor: accent,
                side: const BorderSide(color: accent),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                padding: const EdgeInsets.symmetric(vertical: 14),
              ),
            ),
          ),

          const SizedBox(height: 12),

          Center(child: Text(
            'Changing your account will require re-verification.',
            style: TextStyle(fontSize: 12, color: subtleText),
            textAlign: TextAlign.center,
          )),
        ],
      ),
    );
  }
}

// ─── Searchable Bank Picker Sheet ─────────────────────────────────────────────
class _BankPickerSheet extends StatefulWidget {
  final List<_PaystackBank> banks;
  final _PaystackBank? selectedBank;
  final ValueChanged<_PaystackBank> onSelect;

  const _BankPickerSheet({required this.banks, required this.selectedBank, required this.onSelect});

  @override
  State<_BankPickerSheet> createState() => _BankPickerSheetState();
}

class _BankPickerSheetState extends State<_BankPickerSheet> {
  final _searchController = TextEditingController();
  List<_PaystackBank> _filtered = [];

  @override
  void initState() {
    super.initState();
    _filtered = widget.banks;
    _searchController.addListener(_onSearchChanged);
  }

  @override
  void dispose() {
    _searchController.removeListener(_onSearchChanged);
    _searchController.dispose();
    super.dispose();
  }

  void _onSearchChanged() {
    final q = _searchController.text.toLowerCase().trim();
    setState(() {
      _filtered = q.isEmpty ? widget.banks : widget.banks.where((b) => b.name.toLowerCase().contains(q)).toList();
    });
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;
    final sheetBg = isDark ? const Color(0xFF132030) : Colors.white;
    final cardColor = isDark ? const Color(0xFF1E2A3A) : const Color(0xFFF5F7FA);
    const accent = Color(0xFF4A90E2);
    final subtleText = isDark ? Colors.white54 : Colors.grey[600];

    return DraggableScrollableSheet(
      initialChildSize: 0.7, minChildSize: 0.4, maxChildSize: 0.92, expand: false,
      builder: (_, scrollController) => Container(
        decoration: BoxDecoration(
          color: sheetBg,
          borderRadius: const BorderRadius.vertical(top: Radius.circular(24)),
          boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.15), blurRadius: 20, offset: const Offset(0, -4))],
        ),
        child: Column(children: [
          // Drag handle
          Padding(
            padding: const EdgeInsets.only(top: 12, bottom: 4),
            child: Container(width: 40, height: 4,
              decoration: BoxDecoration(color: isDark ? Colors.white24 : Colors.grey[300], borderRadius: BorderRadius.circular(2))),
          ),
          // Header
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
            child: Row(children: [
              const Icon(Icons.account_balance_rounded, color: accent, size: 20),
              const SizedBox(width: 8),
              Text('Select Bank', style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold)),
              const Spacer(),
              Text('${_filtered.length} banks', style: TextStyle(color: subtleText, fontSize: 12)),
            ]),
          ),
          // Search
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
            child: TextField(
              controller: _searchController,
              autofocus: true,
              style: theme.textTheme.bodyLarge,
              decoration: InputDecoration(
                prefixIcon: Icon(Icons.search, color: subtleText, size: 20),
                suffixIcon: _searchController.text.isNotEmpty
                    ? IconButton(icon: Icon(Icons.clear, color: subtleText, size: 18), onPressed: () => _searchController.clear())
                    : null,
                hintText: 'Search banks…',
                hintStyle: TextStyle(color: subtleText, fontSize: 14),
                filled: true, fillColor: cardColor,
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide.none),
                contentPadding: const EdgeInsets.symmetric(vertical: 12, horizontal: 4),
              ),
            ),
          ),
          const SizedBox(height: 8),
          Divider(height: 1, thickness: 1, color: isDark ? Colors.white12 : Colors.grey[200]),
          // Bank list
          Expanded(
            child: _filtered.isEmpty
                ? Center(child: Column(mainAxisSize: MainAxisSize.min, children: [
                    Icon(Icons.search_off_rounded, size: 40, color: subtleText),
                    const SizedBox(height: 8),
                    Text('No banks match your search', style: TextStyle(color: subtleText)),
                  ]))
                : ListView.builder(
                    controller: scrollController,
                    itemCount: _filtered.length,
                    itemBuilder: (_, i) {
                      final bank = _filtered[i];
                      final isSelected = widget.selectedBank?.code == bank.code;
                      return ListTile(
                        leading: CircleAvatar(
                          radius: 18,
                          backgroundColor: accent.withOpacity(isSelected ? 1.0 : 0.1),
                          child: Text(bank.name[0],
                              style: TextStyle(color: isSelected ? Colors.white : accent, fontWeight: FontWeight.bold, fontSize: 13)),
                        ),
                        title: Text(bank.name, style: theme.textTheme.bodyLarge?.copyWith(fontWeight: isSelected ? FontWeight.bold : FontWeight.normal)),
                        subtitle: Text('Code: ${bank.code}', style: TextStyle(color: subtleText, fontSize: 11)),
                        trailing: isSelected ? const Icon(Icons.check_circle_rounded, color: accent) : null,
                        onTap: () => widget.onSelect(bank),
                      );
                    },
                  ),
          ),
        ]),
      ),
    );
  }
}
