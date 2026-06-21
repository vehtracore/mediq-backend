import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:intl/intl.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';

import '../../../core/api/dio_client.dart';
import '../data/vault_record.dart';
import '../data/vault_repository.dart';

// ─────────────────────────────────────────────────────────────────────────────
// Color tokens
// ─────────────────────────────────────────────────────────────────────────────
const _kBlue = Color(0xFF4A90E2);
const _kTeal = Color(0xFF50E3C2);
const _kAiFrom = Color(0xFF6C47FF);
const _kAiTo = Color(0xFF4A90E2);
const _kSelectionBg = Color(0xFF1A3A6B); // deep navy for selection AppBar

// ─────────────────────────────────────────────────────────────────────────────
// Selection state — held in a simple StateProvider so the Set survives
// rebuilds triggered by historyAsync without resetting.
// ─────────────────────────────────────────────────────────────────────────────

final _selectedIdsProvider = StateProvider<Set<String>>((ref) => {});

// ─────────────────────────────────────────────────────────────────────────────
// VaultScreen  (ConsumerStatefulWidget for loading-overlay control)
// ─────────────────────────────────────────────────────────────────────────────

class VaultScreen extends ConsumerStatefulWidget {
  const VaultScreen({super.key});

  @override
  ConsumerState<VaultScreen> createState() => _VaultScreenState();
}

class _VaultScreenState extends ConsumerState<VaultScreen> {
  bool _isExporting = false;
  bool _isDeleting = false;

  // ── Derived helpers ────────────────────────────────────────────────────────
  Set<String> get _selectedIds => ref.read(_selectedIdsProvider);
  bool get isSelectionMode => ref.watch(_selectedIdsProvider).isNotEmpty;

  // ── Toggle a record in/out of the selection ────────────────────────────────
  void _toggleSelection(String id) {
    ref.read(_selectedIdsProvider.notifier).update((current) {
      final next = Set<String>.from(current);
      if (next.contains(id)) {
        next.remove(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  // ── Clear all selections ───────────────────────────────────────────────────
  void _clearSelection() {
    ref.read(_selectedIdsProvider.notifier).state = {};
  }

  // ── Export a set of IDs to PDF via the backend ────────────────────────────
  Future<void> _exportRecords(Set<String> ids) async {
    if (ids.isEmpty) return;

    setState(() => _isExporting = true);
    try {
      final dio = ref.read(dioProvider);

      if (kDebugMode) {
        debugPrint('📤 [Vault] Exporting ${ids.length} record(s) → POST /api/v1/vault/export');
      }

      final response = await dio.post<List<int>>(
        '/api/v1/vault/export',
        data: {'record_ids': ids.toList()},
        options: Options(responseType: ResponseType.bytes),
      );

      final bytes = response.data;
      if (bytes == null || bytes.isEmpty) {
        throw Exception('Empty PDF returned from server.');
      }

      // Write to temp dir
      final tmpDir = await getTemporaryDirectory();
      final fileName = 'mdq_records_${DateTime.now().millisecondsSinceEpoch}.pdf';
      final file = File('${tmpDir.path}/$fileName');
      await file.writeAsBytes(bytes, flush: true);

      if (kDebugMode) {
        debugPrint('📄 [Vault] PDF written → ${file.path}');
      }

      // Share / save natively
      await Share.shareXFiles(
        [XFile(file.path, mimeType: 'application/pdf')],
        subject: 'VehtraCore Health Vault Records',
      );

      _clearSelection();
    } on DioException catch (e) {
      final detail = e.response?.data is Map
          ? e.response!.data['detail']
          : e.message;
      _showSnack('Export failed: ${detail ?? 'Network error'}', isError: true);
    } catch (e) {
      _showSnack('Export failed: $e', isError: true);
    } finally {
      if (mounted) setState(() => _isExporting = false);
    }
  }

  // ── Delete placeholder ─────────────────────────────────────────────────────
  Future<void> _deleteRecord(String id) async {
    final confirm = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text("Are you sure?"),
        content: const Text("Do you really want to delete this item? This action cannot be undone."),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text("No, keep it")),
          TextButton(onPressed: () => Navigator.pop(ctx, true), child: const Text("Yes, delete", style: TextStyle(color: Colors.red))),
        ],
      ),
    );
    if (confirm != true) return;

    setState(() => _isDeleting = true);
    try {
      final dio = ref.read(dioProvider);
      final response = await dio.delete('/api/v1/vault/record/$id');
      if (response.statusCode == 200) {
        ref.invalidate(vaultHistoryProvider);
        _showSnack('Record deleted successfully.', isError: false);
      }
    } catch (e) {
      _showSnack('Delete failed: $e', isError: true);
    } finally {
      if (mounted) setState(() => _isDeleting = false);
    }
  }

  // ── Snack helper ───────────────────────────────────────────────────────────
  void _showSnack(String msg, {required bool isError}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(msg, style: GoogleFonts.lato(fontSize: 13)),
        backgroundColor: isError ? const Color(0xFFE57373) : _kBlue,
        behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
        margin: const EdgeInsets.fromLTRB(16, 0, 16, 12),
      ),
    );
  }

  // ─────────────────────────────────────────────────────────────────────────
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;
    final historyAsync = ref.watch(vaultHistoryProvider);
    final selectedIds = ref.watch(_selectedIdsProvider);
    final inSelectionMode = selectedIds.isNotEmpty;

    return Stack(
      children: [
        Scaffold(
          backgroundColor: theme.scaffoldBackgroundColor,
          body: RefreshIndicator(
            onRefresh: () async => ref.refresh(vaultHistoryProvider.future),
            color: _kBlue,
            child: CustomScrollView(
              slivers: [
                // ── App Bar ────────────────────────────────────────────────────
              SliverAppBar(
                floating: true,
                snap: true,
                backgroundColor: inSelectionMode
                    ? _kSelectionBg
                    : (isDark ? const Color(0xFF1E1E1E) : Colors.white),
                elevation: inSelectionMode ? 2 : 0,
                // Leading: close-selection button when active
                leading: inSelectionMode
                    ? IconButton(
                        icon: const Icon(Icons.close_rounded, color: Colors.white),
                        tooltip: 'Clear selection',
                        onPressed: _clearSelection,
                      )
                    : null,
                title: inSelectionMode
                    ? Text(
                        '${selectedIds.length} Selected',
                        style: GoogleFonts.poppins(
                          fontSize: 18,
                          fontWeight: FontWeight.w600,
                          color: Colors.white,
                        ),
                      )
                    : Text(
                        'Records',
                        style: theme.textTheme.titleLarge,
                      ),
                actions: [
                  if (inSelectionMode) ...[
                    // Download / export selected
                    IconButton(
                      icon: const Icon(Icons.download_rounded, color: Colors.white),
                      tooltip: 'Export selected as PDF',
                      onPressed: () => _exportRecords(selectedIds),
                    ),
                    const SizedBox(width: 4),
                  ],
                ],
              ),

              // ── Selection hint banner ──────────────────────────────────────
              if (inSelectionMode)
                SliverToBoxAdapter(
                  child: Container(
                    color: _kSelectionBg.withValues(alpha: 0.08),
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                    child: Row(
                      children: [
                        const Icon(Icons.info_outline_rounded, size: 14, color: _kBlue),
                        const SizedBox(width: 6),
                        Text(
                          'Long-press cards to select · tap Download to export',
                          style: GoogleFonts.lato(fontSize: 12, color: _kBlue),
                        ),
                      ],
                    ),
                  ),
                ),

              // ── Body ───────────────────────────────────────────────────────
              historyAsync.when(
                loading: () => const SliverFillRemaining(
                  child: Center(
                    child: CircularProgressIndicator(color: _kBlue),
                  ),
                ),
                error: (err, _) => SliverFillRemaining(
                  child: _ErrorState(
                    message: err.toString().replaceFirst('Exception: ', ''),
                    onRetry: () => ref.invalidate(vaultHistoryProvider),
                  ),
                ),
                data: (records) {
                  if (records.isEmpty) {
                    return const SliverFillRemaining(child: _EmptyState());
                  }
                  return SliverPadding(
                    padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
                    sliver: SliverList(
                      delegate: SliverChildBuilderDelegate(
                        (context, i) {
                          final record = records[i];
                          final isSelected = selectedIds.contains(record.id);

                          return Padding(
                            padding: const EdgeInsets.only(bottom: 12),
                            child: _SelectableCardWrapper(
                              recordId: record.id,
                              isSelected: isSelected,
                              onLongPress: () => _toggleSelection(record.id),
                              onTap: inSelectionMode
                                  ? () => _toggleSelection(record.id)
                                  : null,
                              child: record.isConsultation
                                  ? ConsultationCard(
                                      record: record,
                                      isSelected: isSelected,
                                      onExportPdf: () =>
                                          _exportRecords({record.id}),
                                    )
                                  : AISummaryCard(
                                      record: record,
                                      isSelected: isSelected,
                                      onExportPdf: () =>
                                          _exportRecords({record.id}),
                                      onDelete: () => _deleteRecord(record.id),
                                    ),
                            ),
                          );
                        },
                        childCount: records.length,
                      ),
                    ),
                  );
                },
              ),
              ],
            ),
          ),
        ),

        // ── Loading overlay ────────────────────────────────────────────────
        if (_isExporting || _isDeleting)
          Container(
            color: Colors.black54,
            child: Center(
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 22),
                decoration: BoxDecoration(
                  color: isDark ? const Color(0xFF252525) : Colors.white,
                  borderRadius: BorderRadius.circular(16),
                  boxShadow: [
                    BoxShadow(
                      color: Colors.black.withValues(alpha: 0.2),
                      blurRadius: 20,
                    ),
                  ],
                ),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const CircularProgressIndicator(color: _kBlue),
                    const SizedBox(height: 16),
                    Text(
                      _isExporting ? 'Generating PDF…' : 'Deleting…',
                      style: GoogleFonts.poppins(
                        fontSize: 14,
                        fontWeight: FontWeight.w500,
                        color: isDark ? Colors.white : const Color(0xFF2D3436),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
      ],
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// _SelectableCardWrapper — handles long-press + selection highlight overlay
// ─────────────────────────────────────────────────────────────────────────────

class _SelectableCardWrapper extends StatelessWidget {
  final String recordId;
  final bool isSelected;
  final VoidCallback onLongPress;
  final VoidCallback? onTap;
  final Widget child;

  const _SelectableCardWrapper({
    required this.recordId,
    required this.isSelected,
    required this.onLongPress,
    required this.onTap,
    required this.child,
  });

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        GestureDetector(
          onLongPress: onLongPress,
          onTap: onTap,
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 200),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(16),
              border: isSelected
                  ? Border.all(color: _kBlue, width: 2)
                  : null,
            ),
            child: child,
          ),
        ),
        // ── Checkmark badge when selected ─────────────────────────────────
        if (isSelected)
          Positioned(
            top: 8,
            right: 8,
            child: Container(
              width: 24,
              height: 24,
              decoration: const BoxDecoration(
                color: _kBlue,
                shape: BoxShape.circle,
              ),
              child: const Icon(Icons.check_rounded,
                  size: 14, color: Colors.white),
            ),
          ),
      ],
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// ConsultationCard
// ─────────────────────────────────────────────────────────────────────────────

class ConsultationCard extends StatelessWidget {
  final VaultRecord record;
  final bool isSelected;
  final VoidCallback onExportPdf;

  const ConsultationCard({
    super.key,
    required this.record,
    this.isSelected = false,
    required this.onExportPdf,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;
    final cardBg = isSelected
        ? (isDark
            ? const Color(0xFF1A3A5C)
            : const Color(0xFFE8F0FD))
        : (isDark ? const Color(0xFF252525) : Colors.white);
    final borderColor =
        isDark ? Colors.white12 : const Color(0xFFE8EEF6);

    return Container(
      decoration: BoxDecoration(
        color: cardBg,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: borderColor, width: 1),
        boxShadow: isDark
            ? []
            : [
                BoxShadow(
                  color: Colors.black.withValues(alpha: 0.05),
                  blurRadius: 12,
                  offset: const Offset(0, 4),
                ),
              ],
      ),
      child: Theme(
        data: theme.copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          tilePadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
          childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
          // ── Trailing: popup menu ─────────────────────────────────────────
          trailing: PopupMenuButton<String>(
            icon: Icon(Icons.more_vert_rounded,
                size: 18, color: isDark ? Colors.white38 : Colors.grey[500]),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
            onSelected: (value) {
              if (value == 'export_pdf') onExportPdf();
            },
            itemBuilder: (_) => [
              PopupMenuItem(
                value: 'export_pdf',
                child: Row(
                  children: [
                    const Icon(Icons.picture_as_pdf_rounded,
                        size: 16, color: _kBlue),
                    const SizedBox(width: 10),
                    Text('Export PDF',
                        style: GoogleFonts.lato(fontSize: 13)),
                  ],
                ),
              ),
            ],
          ),
          title: Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Container(
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: const Color(0xFF4A90E2).withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: const Icon(Icons.medical_services_outlined,
                    color: _kBlue, size: 20),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Consultation',
                      style: GoogleFonts.poppins(
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                        color: _kBlue,
                        letterSpacing: 0.3,
                      ),
                    ),
                    Text(
                      _formatDate(record.date),
                      style: GoogleFonts.lato(
                        fontSize: 12,
                        color: isDark ? Colors.white38 : Colors.grey[500],
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      record.topicOrReason,
                      style: GoogleFonts.lato(
                        fontSize: 13,
                        fontWeight: FontWeight.w500,
                        color: isDark ? Colors.white70 : const Color(0xFF2D3436),
                      ),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ],
                ),
              ),
              if (record.doctorName != null) ...[
                const SizedBox(width: 8),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(
                    color: _kBlue.withValues(alpha: 0.08),
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(Icons.person_rounded,
                          size: 12, color: _kBlue),
                      const SizedBox(width: 4),
                      Text(
                        '${record.doctorName}',
                        style: GoogleFonts.lato(
                          fontSize: 11,
                          fontWeight: FontWeight.w600,
                          color: _kBlue,
                        ),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ],
                  ),
                ),
              ],
            ],
          ),
          children: [
            const Divider(height: 1),
            const SizedBox(height: 12),
            if (record.details != null && record.details!.isNotEmpty) ...[
              Align(
                alignment: Alignment.centerLeft,
                child: Text(
                  'Clinical Notes',
                  style: GoogleFonts.poppins(
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                    color: isDark ? Colors.white54 : Colors.grey[500],
                    letterSpacing: 0.5,
                  ),
                ),
              ),
              const SizedBox(height: 6),
              Align(
                alignment: Alignment.centerLeft,
                child: MarkdownBody(
                  data: record.details!,
                  styleSheet: MarkdownStyleSheet(
                    p: GoogleFonts.lato(
                      fontSize: 14,
                      height: 1.55,
                      color: isDark
                          ? Colors.white.withOpacity(0.87)
                          : const Color(0xFF2D3436),
                    ),
                  ),
                ),
              ),
            ],
            if (record.prescriptions != null &&
                record.prescriptions!.isNotEmpty) ...[
              const SizedBox(height: 14),
              Text(
                'Prescriptions & Medications',
                style: GoogleFonts.poppins(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  color: const Color(0xFF008080), // Subtle teal
                  letterSpacing: 0.5,
                ),
              ),
              const SizedBox(height: 6),
              Align(
                alignment: Alignment.centerLeft,
                child: Text(
                  record.prescriptions!,
                  style: GoogleFonts.lato(
                    fontSize: 14,
                    color: isDark ? Colors.white70 : Colors.black87,
                  ),
                ),
              ),
            ],
            if (record.referrals != null && record.referrals!.isNotEmpty) ...[
              const SizedBox(height: 14),
              Text(
                'Referrals',
                style: GoogleFonts.poppins(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  color: isDark ? Colors.white54 : Colors.grey[600],
                  letterSpacing: 0.5,
                ),
              ),
              const SizedBox(height: 6),
              Align(
                alignment: Alignment.centerLeft,
                child: Text(
                  record.referrals!,
                  style: GoogleFonts.lato(
                    fontSize: 14,
                    color: isDark ? Colors.white70 : Colors.black87,
                  ),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// AISummaryCard
// ─────────────────────────────────────────────────────────────────────────────

class AISummaryCard extends StatelessWidget {
  final VaultRecord record;
  final bool isSelected;
  final VoidCallback onExportPdf;
  final VoidCallback onDelete;

  const AISummaryCard({
    super.key,
    required this.record,
    this.isSelected = false,
    required this.onExportPdf,
    required this.onDelete,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;

    final cardBg = isSelected
        ? (isDark ? const Color(0xFF1E1535) : const Color(0xFFEDE7F6))
        : (isDark ? const Color(0xFF1A1A2E) : const Color(0xFFF5F3FF));
    final borderColor = isDark
        ? const Color(0xFF6C47FF).withValues(alpha: 0.25)
        : const Color(0xFF6C47FF).withValues(alpha: 0.18);

    return Container(
      decoration: BoxDecoration(
        color: cardBg,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: borderColor, width: 1),
        boxShadow: isDark
            ? []
            : [
                BoxShadow(
                  color: const Color(0xFF6C47FF).withValues(alpha: 0.06),
                  blurRadius: 12,
                  offset: const Offset(0, 4),
                ),
              ],
      ),
      child: Theme(
        data: theme.copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          tilePadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
          childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
          // ── Trailing: popup menu ─────────────────────────────────────────
          trailing: PopupMenuButton<String>(
            icon: Icon(Icons.more_vert_rounded,
                size: 18,
                color: isDark ? Colors.white38 : Colors.grey[500]),
            shape:
                RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
            onSelected: (value) {
              if (value == 'export_pdf') onExportPdf();
              if (value == 'delete') onDelete();
            },
            itemBuilder: (_) => [
              PopupMenuItem(
                value: 'export_pdf',
                child: Row(
                  children: [
                    const Icon(Icons.picture_as_pdf_rounded,
                        size: 16, color: _kBlue),
                    const SizedBox(width: 10),
                    Text('Export PDF',
                        style: GoogleFonts.lato(fontSize: 13)),
                  ],
                ),
              ),
              PopupMenuItem(
                value: 'delete',
                child: Row(
                  children: [
                    const Icon(Icons.delete_outline_rounded,
                        size: 16, color: Color(0xFFE57373)),
                    const SizedBox(width: 10),
                    Text('Delete',
                        style: GoogleFonts.lato(
                            fontSize: 13, color: const Color(0xFFE57373))),
                  ],
                ),
              ),
            ],
          ),
          title: Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Container(
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: _kAiFrom,
                  borderRadius: BorderRadius.circular(10),
                ),
                child: const Icon(Icons.auto_awesome_rounded,
                    color: Colors.white, size: 18),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'AI Health Summary',
                      style: GoogleFonts.poppins(
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                        color: _kAiFrom,
                      ),
                    ),
                    Text(
                      _formatDate(record.date),
                      style: GoogleFonts.lato(
                        fontSize: 12,
                        color: isDark ? Colors.white38 : Colors.grey[500],
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      record.topicOrReason,
                      style: GoogleFonts.lato(
                        fontSize: 13,
                        fontWeight: FontWeight.w500,
                        color: isDark
                            ? const Color(0xFFB39DDB)
                            : const Color(0xFF5E35B1),
                      ),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ],
                ),
              ),
            ],
          ),
          children: [
            Divider(
              height: 1,
              color: isDark
                  ? Colors.white10
                  : const Color(0xFF6C47FF).withValues(alpha: 0.15),
            ),
            const SizedBox(height: 12),
            if (record.details != null && record.details!.isNotEmpty)
              Align(
                alignment: Alignment.centerLeft,
                child: MarkdownBody(
                  data: record.details!,
                  styleSheet: MarkdownStyleSheet(
                    p: GoogleFonts.lato(
                      fontSize: 14,
                      height: 1.6,
                      color:
                          isDark ? Colors.white70 : const Color(0xFF2D3436),
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Sub-widgets (unchanged from original)
// ─────────────────────────────────────────────────────────────────────────────

class _SectionLabel extends StatelessWidget {
  final IconData icon;
  final String label;
  final Color iconColor;
  final bool isDark;

  const _SectionLabel({
    required this.icon,
    required this.label,
    required this.iconColor,
    required this.isDark,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Icon(icon, size: 14, color: iconColor),
        const SizedBox(width: 6),
        Text(
          label,
          style: GoogleFonts.poppins(
            fontSize: 11,
            fontWeight: FontWeight.w600,
            color: isDark ? Colors.white54 : Colors.grey[600],
            letterSpacing: 0.4,
          ),
        ),
      ],
    );
  }
}

class _PrescriptionChip extends StatelessWidget {
  final dynamic raw;
  final bool isDark;

  const _PrescriptionChip({required this.raw, required this.isDark});

  @override
  Widget build(BuildContext context) {
    String label;
    if (raw is Map) {
      final drug = raw['drug'] ?? raw['name'] ?? '';
      final dosage = raw['dosage'] ?? raw['dose'] ?? '';
      label = dosage.isNotEmpty ? '$drug · $dosage' : drug.toString();
    } else {
      label = raw.toString();
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      decoration: BoxDecoration(
        color: const Color(0xFF27AE60)
            .withValues(alpha: isDark ? 0.15 : 0.1),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(
          color: const Color(0xFF27AE60).withValues(alpha: 0.35),
        ),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.medication_rounded,
              size: 12, color: Color(0xFF27AE60)),
          const SizedBox(width: 5),
          Text(
            label,
            style: GoogleFonts.lato(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: isDark
                  ? const Color(0xFF81C784)
                  : const Color(0xFF1B5E20),
            ),
          ),
        ],
      ),
    );
  }
}

class _ReferralTile extends StatelessWidget {
  final dynamic raw;
  final bool isDark;

  const _ReferralTile({required this.raw, required this.isDark});

  @override
  Widget build(BuildContext context) {
    String hospital = '';
    String reason = '';

    if (raw is Map) {
      hospital =
          (raw['hospital'] ?? raw['hospital_name'] ?? '').toString();
      reason = (raw['reason'] ?? raw['note'] ?? '').toString();
    } else {
      hospital = raw.toString();
    }

    return Container(
      margin: const EdgeInsets.only(bottom: 6),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: const Color(0xFFE67E22)
            .withValues(alpha: isDark ? 0.12 : 0.07),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(
          color: const Color(0xFFE67E22).withValues(alpha: 0.3),
        ),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.local_hospital_rounded,
              size: 16, color: Color(0xFFE67E22)),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (hospital.isNotEmpty)
                  Text(
                    hospital,
                    style: GoogleFonts.poppins(
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                      color: isDark
                          ? const Color(0xFFFFCC80)
                          : const Color(0xFF7F4800),
                    ),
                  ),
                if (reason.isNotEmpty)
                  Text(
                    reason,
                    style: GoogleFonts.lato(
                      fontSize: 12,
                      color: isDark ? Colors.white54 : Colors.grey[600],
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Empty / Error states
// ─────────────────────────────────────────────────────────────────────────────

class _EmptyState extends StatelessWidget {
  const _EmptyState();

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Center(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 40),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 90,
              height: 90,
              decoration: BoxDecoration(
                gradient: const LinearGradient(
                  colors: [Color(0xFFE8F4FD), Color(0xFFEDE7F6)],
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                ),
                shape: BoxShape.circle,
                boxShadow: [
                  BoxShadow(
                    color: _kBlue.withValues(alpha: 0.12),
                    blurRadius: 20,
                    offset: const Offset(0, 8),
                  ),
                ],
              ),
              child: const Icon(Icons.health_and_safety_rounded,
                  size: 44, color: _kBlue),
            ),
            const SizedBox(height: 24),
            Text(
              'Your Vault is Empty',
              style: GoogleFonts.poppins(
                fontSize: 18,
                fontWeight: FontWeight.bold,
                color: isDark ? Colors.white : const Color(0xFF2D3436),
              ),
            ),
            const SizedBox(height: 10),
            Text(
              'Your AI chat summaries and consultation records\nwill appear here.',
              textAlign: TextAlign.center,
              style: GoogleFonts.lato(
                fontSize: 14,
                height: 1.6,
                color: isDark ? Colors.white54 : Colors.grey[500],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ErrorState extends StatelessWidget {
  final String message;
  final VoidCallback onRetry;

  const _ErrorState({required this.message, required this.onRetry});

  /// Converts a potentially verbose exception string into a short,
  /// user-friendly message that won't cause RenderFlex overflows.
  String _friendlyMessage(String raw) {
    if (raw.isEmpty) return 'Please check your connection and try again.';
    // Strip noisy HTTP error descriptions — show only the first sentence / line
    final firstLine = raw.split('\n').first.trim();
    // If the message is still very long (e.g. full stack dump), truncate it
    if (firstLine.length > 120) {
      return 'Something went wrong. Please try again.';
    }
    return firstLine;
  }

  @override
  Widget build(BuildContext context) {
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.symmetric(horizontal: 32, vertical: 24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.cloud_off_rounded,
                size: 56, color: Color(0xFFE57373)),
            const SizedBox(height: 16),
            Text(
              'Could not load Records',
              style: GoogleFonts.poppins(
                  fontSize: 16, fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: 8),
            Text(
              _friendlyMessage(message),
              textAlign: TextAlign.center,
              style: GoogleFonts.lato(fontSize: 13, color: Colors.grey),
            ),
            const SizedBox(height: 24),
            ElevatedButton.icon(
              onPressed: onRetry,
              icon: const Icon(Icons.refresh_rounded),
              label: const Text('Try Again'),
            ),
          ],
        ),
      ),
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Shared utility
// ─────────────────────────────────────────────────────────────────────────────

String _formatDate(DateTime dt) {
  final local = dt.toLocal();
  final now = DateTime.now();
  final diff = now.difference(local);

  if (diff.inDays == 0) return 'Today · ${DateFormat.jm().format(local)}';
  if (diff.inDays == 1) return 'Yesterday · ${DateFormat.jm().format(local)}';
  if (diff.inDays < 7) {
    return '${DateFormat('EEEE').format(local)} · ${DateFormat.jm().format(local)}';
  }
  return DateFormat('d MMM yyyy · h:mm a').format(local);
}
