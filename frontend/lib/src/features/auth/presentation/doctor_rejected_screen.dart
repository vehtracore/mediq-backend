import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:google_fonts/google_fonts.dart';
import '../data/auth_repository.dart';
import 'auth_controller.dart';

class DoctorRejectedScreen extends ConsumerStatefulWidget {
  const DoctorRejectedScreen({super.key});

  @override
  ConsumerState<DoctorRejectedScreen> createState() =>
      _DoctorRejectedScreenState();
}

class _DoctorRejectedScreenState extends ConsumerState<DoctorRejectedScreen> {
  // State
  bool _isLoading = true;
  bool _isSubmitting = false;
  String? _rejectionReason;
  String? _errorMessage;

  // Form
  final _formKey = GlobalKey<FormState>();
  final _licenseCtrl = TextEditingController();

  // ── Colour palette ──────────────────────────────────────────────────────────
  static const _bgColor = Color(0xFF0D0D1A);
  static const _cardColor = Color(0xFF161628);
  static const _accentRed = Color(0xFFE94560);
  static const _accentBlue = Color(0xFF4A90E2);
  static const _textPrimary = Color(0xFFF0F0F0);
  static const _textMuted = Color(0xFF8892A4);

  @override
  void initState() {
    super.initState();
    _loadRejectionDetails();
  }

  @override
  void dispose() {
    _licenseCtrl.dispose();
    super.dispose();
  }

  // ── Load the doctor's rejection reason from the backend ─────────────────────
  Future<void> _loadRejectionDetails() async {
    try {
      final doctor =
          await ref.read(authRepositoryProvider).getMyDoctorProfile();
      if (!mounted) return;
      setState(() {
        _rejectionReason = doctor.rejectionReason;
        _isLoading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _rejectionReason = null;
        _isLoading = false;
      });
    }
  }

  // ── Submit re-application ────────────────────────────────────────────────────
  Future<void> _submitReapplication() async {
    if (!_formKey.currentState!.validate()) return;

    setState(() {
      _isSubmitting = true;
      _errorMessage = null;
    });

    try {
      await ref.read(authRepositoryProvider).reapply(
            licenseNumber: _licenseCtrl.text.trim().isEmpty
                ? null
                : _licenseCtrl.text.trim(),
          );

      if (!mounted) return;

      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: const Text(
            '✅ Application resubmitted! Your documents are under review.',
          ),
          backgroundColor: Colors.green.shade700,
          behavior: SnackBarBehavior.floating,
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        ),
      );

      // Route to splash to allow primary guard to check status
      context.go('/');
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _errorMessage = e.toString().replaceFirst('Exception: ', '');
        _isSubmitting = false;
      });
    }
  }

  // ── Logout ───────────────────────────────────────────────────────────────────
  Future<void> _logout() async {
    await ref.read(authControllerProvider.notifier).logout();
    if (mounted) context.go('/auth');
  }

  // ─────────────────────────────────────────────────────────────────────────────
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _bgColor,
      body: _isLoading
          ? const Center(child: CircularProgressIndicator(color: _accentBlue))
          : SafeArea(
              child: CustomScrollView(
                slivers: [
                  // ── AppBar ──────────────────────────────────────────────────
                  SliverAppBar(
                    backgroundColor: _bgColor,
                    pinned: true,
                    elevation: 0,
                    title: Row(
                      children: [
                        const Icon(Icons.health_and_safety,
                            color: _accentBlue, size: 22),
                        const SizedBox(width: 8),
                        Text(
                          'MDQ+',
                          style: GoogleFonts.poppins(
                            color: _textPrimary,
                            fontWeight: FontWeight.bold,
                            fontSize: 18,
                          ),
                        ),
                      ],
                    ),
                    actions: [
                      TextButton.icon(
                        onPressed: _logout,
                        icon: const Icon(Icons.logout,
                            color: _textMuted, size: 18),
                        label: Text('Logout',
                            style: GoogleFonts.poppins(
                                color: _textMuted, fontSize: 13)),
                      ),
                    ],
                  ),

                  SliverPadding(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 24, vertical: 16),
                    sliver: SliverList(
                      delegate: SliverChildListDelegate([
                        // ── Status badge ───────────────────────────────────────
                        Center(
                          child: Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 14, vertical: 6),
                            decoration: BoxDecoration(
                              color: _accentRed.withOpacity(0.15),
                              borderRadius: BorderRadius.circular(20),
                              border:
                                  Border.all(color: _accentRed.withOpacity(0.4)),
                            ),
                            child: Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                const Icon(Icons.block,
                                    color: _accentRed, size: 14),
                                const SizedBox(width: 6),
                                Text(
                                  'APPLICATION REJECTED',
                                  style: GoogleFonts.poppins(
                                    color: _accentRed,
                                    fontSize: 11,
                                    fontWeight: FontWeight.w600,
                                    letterSpacing: 1.2,
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                        const SizedBox(height: 24),

                        // ── Headline ───────────────────────────────────────────
                        Text(
                          "Let's Fix This",
                          textAlign: TextAlign.center,
                          style: GoogleFonts.poppins(
                            color: _textPrimary,
                            fontSize: 28,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                        const SizedBox(height: 12),
                        Text(
                          'Your verification application was not approved. Review the reason below, correct your information, and resubmit.',
                          textAlign: TextAlign.center,
                          style: GoogleFonts.lato(
                            color: _textMuted,
                            fontSize: 15,
                            height: 1.6,
                          ),
                        ),
                        const SizedBox(height: 32),

                        // ── Rejection reason card ──────────────────────────────
                        Container(
                          width: double.infinity,
                          padding: const EdgeInsets.all(20),
                          decoration: BoxDecoration(
                            color: _cardColor,
                            borderRadius: BorderRadius.circular(16),
                            border: const Border(
                              left: BorderSide(color: _accentRed, width: 4),
                            ),
                          ),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                children: [
                                  const Icon(Icons.info_outline,
                                      color: _accentRed, size: 18),
                                  const SizedBox(width: 8),
                                  Text(
                                    'Reason for Non-Approval',
                                    style: GoogleFonts.poppins(
                                      color: _accentRed,
                                      fontSize: 13,
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                                ],
                              ),
                              const SizedBox(height: 10),
                              Text(
                                _rejectionReason ??
                                    'No specific reason was provided. Please contact support@mdqplus.com.',
                                style: GoogleFonts.lato(
                                  color: _textPrimary,
                                  fontSize: 15,
                                  height: 1.5,
                                ),
                              ),
                            ],
                          ),
                        ),
                        const SizedBox(height: 32),

                        // ── What happens next ──────────────────────────────────
                        const _SectionHeader(label: 'What to do next'),
                        const SizedBox(height: 12),
                        const _StepTile(
                          number: '1',
                          text:
                              'Review the rejection reason carefully and identify what needs correcting.',
                        ),
                        const _StepTile(
                          number: '2',
                          text:
                              'If your MDCN license number was incorrect, update it in the form below.',
                        ),
                        const _StepTile(
                          number: '3',
                          text:
                              'Click "Resubmit Application" to send your corrected information to the MDQ+ admin team for review.',
                        ),
                        const SizedBox(height: 32),

                        // ── Correction form ────────────────────────────────────
                        const _SectionHeader(label: 'Correct Your Information'),
                        const SizedBox(height: 16),
                        Form(
                          key: _formKey,
                          child: Column(
                            children: [
                              // MDCN number field
                              TextFormField(
                                controller: _licenseCtrl,
                                style: GoogleFonts.lato(
                                    color: _textPrimary, fontSize: 15),
                                decoration: InputDecoration(
                                  labelText: 'Corrected MDCN License Number',
                                  labelStyle: GoogleFonts.lato(
                                      color: _textMuted, fontSize: 14),
                                  hintText:
                                      'Leave empty to keep existing value',
                                  hintStyle: GoogleFonts.lato(
                                      color: _textMuted.withOpacity(0.5),
                                      fontSize: 13),
                                  prefixIcon: const Icon(Icons.badge_outlined,
                                      color: _accentBlue),
                                  filled: true,
                                  fillColor: _cardColor,
                                  border: OutlineInputBorder(
                                    borderRadius: BorderRadius.circular(12),
                                    borderSide: BorderSide(
                                        color: _accentBlue.withOpacity(0.3)),
                                  ),
                                  enabledBorder: OutlineInputBorder(
                                    borderRadius: BorderRadius.circular(12),
                                    borderSide: BorderSide(
                                        color: _accentBlue.withOpacity(0.3)),
                                  ),
                                  focusedBorder: OutlineInputBorder(
                                    borderRadius: BorderRadius.circular(12),
                                    borderSide: const BorderSide(
                                        color: _accentBlue, width: 1.5),
                                  ),
                                ),
                              ),
                              const SizedBox(height: 8),
                              Align(
                                alignment: Alignment.centerLeft,
                                child: Text(
                                  'To upload new documents, please contact support@mdqplus.com with your updated files.',
                                  style: GoogleFonts.lato(
                                      color: _textMuted, fontSize: 12),
                                ),
                              ),
                            ],
                          ),
                        ),
                        const SizedBox(height: 24),

                        // ── Error message ──────────────────────────────────────
                        if (_errorMessage != null) ...[
                          Container(
                            padding: const EdgeInsets.all(14),
                            decoration: BoxDecoration(
                              color: _accentRed.withOpacity(0.1),
                              borderRadius: BorderRadius.circular(10),
                              border: Border.all(
                                  color: _accentRed.withOpacity(0.4)),
                            ),
                            child: Row(
                              children: [
                                const Icon(Icons.error_outline,
                                    color: _accentRed, size: 18),
                                const SizedBox(width: 10),
                                Expanded(
                                  child: Text(
                                    _errorMessage!,
                                    style: GoogleFonts.lato(
                                        color: _accentRed, fontSize: 14),
                                  ),
                                ),
                              ],
                            ),
                          ),
                          const SizedBox(height: 16),
                        ],

                        // ── Primary CTA ────────────────────────────────────────
                        SizedBox(
                          width: double.infinity,
                          height: 54,
                          child: ElevatedButton(
                            onPressed:
                                _isSubmitting ? null : _submitReapplication,
                            style: ElevatedButton.styleFrom(
                              backgroundColor: _accentBlue,
                              foregroundColor: Colors.white,
                              disabledBackgroundColor:
                                  _accentBlue.withOpacity(0.4),
                              shape: RoundedRectangleBorder(
                                  borderRadius: BorderRadius.circular(14)),
                              elevation: 0,
                            ),
                            child: _isSubmitting
                                ? const SizedBox(
                                    width: 22,
                                    height: 22,
                                    child: CircularProgressIndicator(
                                        color: Colors.white, strokeWidth: 2.5),
                                  )
                                : Text(
                                    'Resubmit Application',
                                    style: GoogleFonts.poppins(
                                      fontWeight: FontWeight.w600,
                                      fontSize: 15,
                                      letterSpacing: 0.4,
                                    ),
                                  ),
                          ),
                        ),
                        const SizedBox(height: 40),
                      ]),
                    ),
                  ),
                ],
              ),
            ),
    );
  }
}

// ── Helpers ──────────────────────────────────────────────────────────────────

class _SectionHeader extends StatelessWidget {
  final String label;
  const _SectionHeader({required this.label});

  @override
  Widget build(BuildContext context) {
    return Text(
      label.toUpperCase(),
      style: GoogleFonts.poppins(
        color: const Color(0xFF8892A4),
        fontSize: 11,
        fontWeight: FontWeight.w600,
        letterSpacing: 1.4,
      ),
    );
  }
}

class _StepTile extends StatelessWidget {
  final String number;
  final String text;
  const _StepTile({required this.number, required this.text});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 26,
            height: 26,
            decoration: BoxDecoration(
              color: const Color(0xFF4A90E2).withOpacity(0.15),
              shape: BoxShape.circle,
              border: Border.all(
                  color: const Color(0xFF4A90E2).withOpacity(0.5)),
            ),
            alignment: Alignment.center,
            child: Text(
              number,
              style: GoogleFonts.poppins(
                color: const Color(0xFF4A90E2),
                fontWeight: FontWeight.bold,
                fontSize: 12,
              ),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              text,
              style: GoogleFonts.lato(
                color: const Color(0xFF8892A4),
                fontSize: 14,
                height: 1.5,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
