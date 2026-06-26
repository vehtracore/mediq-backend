import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';
import 'package:mediq_app/src/features/reviews/data/review_repository.dart';
import 'package:mediq_app/src/features/patient_dashboard/presentation/widgets/home_widgets.dart';
import 'package:mediq_app/src/core/utils/ui_error_formatter.dart';
import '../data/appointment_model.dart';
import '../data/appointment_repository.dart';
import 'package:mediq_app/presentation/widgets/global_error_widget.dart';

/// Purpose: Drives the state of the user's Schedule/Appointments screen by filtering and presenting
/// a unified list of past and upcoming appointments, ensuring stale history is removed.
///
/// Data Source: Communicates with `appointmentRepositoryProvider` (`getMyAppointments()` API endpoint).
///
/// Invalidation Strategy: Should be explicitly invalidated via `ref.invalidate(myAppointmentsProvider)`
/// on pull-to-refresh, retry taps in GlobalErrorWidget, or immediately after a successful cancellation/booking mutation.
///
/// Error & Loading Annotations: Exceptions thrown by the API (like `DioException`) are caught by Riverpod
/// and translated into clean localized strings by the `GlobalErrorWidget` wrapped around this provider's `error` state.
final myAppointmentsProvider =
    FutureProvider.autoDispose<List<Appointment>>((ref) async {
  final repo = ref.watch(appointmentRepositoryProvider);
  final allAppointments = await repo.getMyAppointments();

  final now = DateTime.now();
  final thirtyDaysAgo = now.subtract(const Duration(days: 30));

  // FILTER LOGIC:
  // 1. Keep ALL future appointments (regardless of status).
  // 2. Keep 'pending' or 'confirmed' appointments (Action needed).
  // 3. For 'completed' or 'cancelled', ONLY keep if less than 30 days old.

  final filtered = allAppointments.where((appt) {
    // General and specialist bookings are paid during their initial booking
    // flow. An abandoned unpaid checkout must not become a schedule item with
    // a second "Pay Now" action. VIP intentionally pays after doctor proposal.
    if (!appt.isVipRequest && appt.paymentStatus != 'paid') {
      return false;
    }

    // Is it in the future? Keep it.
    if (appt.startTime != null && appt.startTime!.isAfter(now)) return true;

    // Is it active/unfinished? Keep it.
    // 'awaiting_payment' = VIP where doctor proposed a time but patient hasn't paid yet.
    if (appt.status == 'pending' ||
        appt.status == 'confirmed' ||
        appt.status == 'awaiting_payment') return true;

    // Is it a recent history item (less than 30 days old)? Keep it.
    if (appt.startTime != null && appt.startTime!.isAfter(thirtyDaysAgo))
      return true;

    // Otherwise, hide it.
    return false;
  }).toList();

  // Sort by date (Newest at the top)
  filtered.sort((a, b) =>
      (b.startTime ?? DateTime(2099)).compareTo(a.startTime ?? DateTime(2099)));

  return filtered;
});

class ScheduleScreen extends ConsumerWidget {
  const ScheduleScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final appointmentsAsync = ref.watch(myAppointmentsProvider);
    final theme = Theme.of(context);

    return Scaffold(
      backgroundColor: theme.scaffoldBackgroundColor, // âœ… Dynamic
      appBar: AppBar(
        title: Text("My Schedule", style: theme.textTheme.titleLarge),
        backgroundColor: theme.appBarTheme.backgroundColor,
        elevation: 0,
        centerTitle: false,
        automaticallyImplyLeading: false,
      ),
      body: appointmentsAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (err, stack) => GlobalErrorWidget(
          error: err,
          onRetry: () => ref.invalidate(myAppointmentsProvider),
        ),
        data: (appointments) {
          if (appointments.isEmpty) {
            return RefreshIndicator(
              onRefresh: () async => ref.refresh(myAppointmentsProvider.future),
              child: ListView(
                children: const [
                  SizedBox(height: 200),
                  Center(child: Text("No appointments yet")),
                ],
              ),
            );
          }
          return RefreshIndicator(
            onRefresh: () async => ref.refresh(myAppointmentsProvider.future),
            child: ListView.separated(
              padding: const EdgeInsets.all(16),
              itemCount: appointments.length,
              separatorBuilder: (_, __) => const SizedBox(height: 16),
              itemBuilder: (context, index) =>
                  _AppointmentCard(appointment: appointments[index]),
            ),
          );
        },
      ),
    );
  }
}

class _AppointmentCard extends ConsumerStatefulWidget {
  final Appointment appointment;
  const _AppointmentCard({required this.appointment});

  @override
  ConsumerState<_AppointmentCard> createState() => _AppointmentCardState();
}

class _AppointmentCardState extends ConsumerState<_AppointmentCard> {
  bool _isLoading = false;
  Timer? _timeGateTimer;

  @override
  void initState() {
    super.initState();
    _scheduleTimeGateRefresh();
  }

  @override
  void didUpdateWidget(covariant _AppointmentCard oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.appointment.startTime != widget.appointment.startTime ||
        oldWidget.appointment.appointmentType !=
            widget.appointment.appointmentType) {
      _scheduleTimeGateRefresh();
    }
  }

  void _scheduleTimeGateRefresh() {
    _timeGateTimer?.cancel();
    final nextBoundary = widget.appointment.nextConsultationBoundary;
    if (nextBoundary == null) return;

    final now = DateTime.now();
    _timeGateTimer = Timer(
      nextBoundary.difference(now) + const Duration(milliseconds: 100),
      () {
        if (!mounted) return;
        setState(() {});
        _scheduleTimeGateRefresh();
      },
    );
  }

  @override
  void dispose() {
    _timeGateTimer?.cancel();
    super.dispose();
  }

  void _showRatingSheet(BuildContext context, WidgetRef ref) {
    int selectedRating = 5;
    bool isReviewLoading = false;
    final commentCtrl = TextEditingController();
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Theme.of(context).cardColor,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setModalState) => Padding(
          padding: EdgeInsets.only(
              bottom: MediaQuery.of(ctx).viewInsets.bottom,
              left: 24,
              right: 24,
              top: 24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text("Rate Your Experience",
                  style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
              const SizedBox(height: 16),
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: List.generate(
                    5,
                    (index) => IconButton(
                        icon: Icon(
                            index < selectedRating
                                ? Icons.star
                                : Icons.star_border,
                            color: Colors.amber,
                            size: 36),
                        onPressed: () =>
                            setModalState(() => selectedRating = index + 1))),
              ),
              const SizedBox(height: 16),
              TextField(
                  controller: commentCtrl,
                  decoration: const InputDecoration(
                      hintText: "Write a review (optional)",
                      border: OutlineInputBorder())),
              const SizedBox(height: 24),
              SizedBox(
                  width: double.infinity,
                  height: 50,
                  child: ElevatedButton(
                      onPressed: isReviewLoading
                          ? null
                          : () async {
                              setModalState(() => isReviewLoading = true);
                              try {
                                await ref
                                    .read(reviewRepositoryProvider)
                                    .submitReview(
                                        appointmentId: widget.appointment.id,
                                        rating: selectedRating,
                                        comment: commentCtrl.text);
                                if (ctx.mounted) Navigator.pop(ctx);
                                ref.invalidate(myAppointmentsProvider);
                              } catch (e) {
                                if (ctx.mounted)
                                  setModalState(() => isReviewLoading = false);
                              }
                            },
                      style: ElevatedButton.styleFrom(
                          backgroundColor: const Color(0xFF4A90E2),
                          foregroundColor: Colors.white),
                      child: isReviewLoading
                          ? const SizedBox(
                              width: 16,
                              height: 16,
                              child: CircularProgressIndicator(
                                  strokeWidth: 2, color: Colors.white))
                          : const Text("Submit Review"))),
              const SizedBox(height: 24),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _showComplaintDialog() async {
    final reasonController = TextEditingController();
    final submitted = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text("Report consultation issue"),
        content: TextField(
          controller: reasonController,
          maxLength: 1000,
          maxLines: 4,
          decoration: const InputDecoration(
            hintText: "Briefly explain what went wrong",
            border: OutlineInputBorder(),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text("Cancel"),
          ),
          ElevatedButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text("Submit"),
          ),
        ],
      ),
    );

    final reason = reasonController.text.trim();
    reasonController.dispose();
    if (submitted != true) return;

    if (reason.isEmpty) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text("Please describe the issue briefly.")),
      );
      return;
    }

    setState(() => _isLoading = true);
    try {
      await ref.read(appointmentRepositoryProvider).raiseAppointmentComplaint(
            id: widget.appointment.id,
            reason: reason,
          );
      ref.invalidate(myAppointmentsProvider);
      ref.invalidate(nextAppointmentProvider);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text("Issue submitted for admin review."),
          backgroundColor: Colors.green,
        ),
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(UIErrorFormatter.getMessage(error)),
          backgroundColor: Colors.red,
        ),
      );
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final appointment = widget.appointment;
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;

    final dayMonth = appointment.startTime != null
        ? DateFormat('MMM dd').format(appointment.startTime!)
        : 'Pending Date';
    final time = appointment.startTime != null
        ? DateFormat('jm').format(appointment.startTime!)
        : 'Pending Time';
    final isConfirmed = appointment.status == 'confirmed';
    final isCompleted = appointment.status == 'completed';
    final isUnpaid = appointment.paymentStatus == 'unpaid';
    final isVipRequest = appointment.isVipRequest;
    final canPatientPay = appointment.canPatientPay;

    Color statusBgColor = Colors.orange.withOpacity(0.1);
    Color statusTextColor = Colors.orange;
    if (isConfirmed) {
      statusBgColor = Colors.green.withOpacity(0.1);
      statusTextColor = Colors.green;
    }
    if (isCompleted) {
      statusBgColor = Colors.blue.withOpacity(0.1);
      statusTextColor = Colors.blue;
    }
    if (appointment.status == 'cancelled') {
      statusBgColor = Colors.grey.shade200;
      statusTextColor = Colors.grey.shade700;
    }
    if (appointment.isNoShow) {
      statusBgColor = Colors.red.withOpacity(0.1);
      statusTextColor = Colors.red.shade700;
    }
    // VIP: doctor proposed a time, patient needs to pay
    if (appointment.status == 'awaiting_payment') {
      statusBgColor = const Color(0xFF7C3AED).withOpacity(0.1);
      statusTextColor = const Color(0xFF7C3AED);
    }

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: theme.cardTheme.color, // âœ… Dynamic Card
        borderRadius: BorderRadius.circular(16),
        boxShadow: isDark
            ? []
            : [
                BoxShadow(
                    color: Colors.grey.withOpacity(0.05),
                    blurRadius: 10,
                    offset: const Offset(0, 4))
              ],
      ),
      child: Column(
        children: [
          Row(
            children: [
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                decoration: BoxDecoration(
                    color: const Color(0xFF4A90E2).withOpacity(0.1),
                    borderRadius: BorderRadius.circular(12)),
                child: Column(children: [
                  Text(dayMonth.split(' ')[1],
                      style: const TextStyle(
                          fontSize: 20,
                          fontWeight: FontWeight.bold,
                          color: Color(0xFF4A90E2))),
                  Text(dayMonth.split(' ')[0],
                      style: const TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.bold,
                          color: Color(0xFF4A90E2))),
                ]),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(time,
                          style: const TextStyle(
                              fontSize: 12, color: Colors.grey)),
                      const SizedBox(height: 4),
                      Text(appointment.doctorName,
                          style: theme.textTheme.titleMedium
                              ?.copyWith(fontWeight: FontWeight.bold)),
                      const SizedBox(height: 6),
                      Wrap(
                        spacing: 6,
                        runSpacing: 6,
                        children: [
                          Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 8, vertical: 4),
                            decoration: BoxDecoration(
                                color: statusBgColor,
                                borderRadius: BorderRadius.circular(8)),
                            child: Text(appointment.statusLabel,
                                style: TextStyle(
                                    color: statusTextColor,
                                    fontSize: 10,
                                    fontWeight: FontWeight.bold)),
                          ),
                          Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 8, vertical: 4),
                            decoration: BoxDecoration(
                              color: theme.colorScheme.surfaceContainerHighest,
                              borderRadius: BorderRadius.circular(8),
                            ),
                            child: Text(
                              appointment.typeLabel,
                              style: theme.textTheme.labelSmall,
                            ),
                          ),
                          if (appointment.refundStatus == 'pending' ||
                              appointment.refundStatus == 'awaiting_admin')
                            Container(
                              padding: const EdgeInsets.symmetric(
                                  horizontal: 8, vertical: 4),
                              decoration: BoxDecoration(
                                color: Colors.amber.withOpacity(0.15),
                                borderRadius: BorderRadius.circular(8),
                              ),
                              child: Text(
                                'REFUND PENDING REVIEW',
                                style: TextStyle(
                                  color: Colors.amber.shade900,
                                  fontSize: 10,
                                  fontWeight: FontWeight.bold,
                                ),
                              ),
                            ),
                        ],
                      ),
                    ]),
              ),
            ],
          ),
          if (appointment.status != 'cancelled') ...[
            const SizedBox(height: 12),
            FittedBox(
              fit: BoxFit.scaleDown,
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  if (appointment.canPatientCancel)
                    TextButton(
                        onPressed: () async {
                          final confirm = await showDialog<bool>(
                            context: context,
                            builder: (ctx) => AlertDialog(
                              title: const Text("Cancel Consultation"),
                              content: const Text(
                                  "Are you sure you want to cancel this consultation?"),
                              actions: [
                                TextButton(
                                    onPressed: () => Navigator.pop(ctx, false),
                                    child: const Text("Keep")),
                                TextButton(
                                    onPressed: () => Navigator.pop(ctx, true),
                                    child: const Text("Cancel",
                                        style: TextStyle(color: Colors.red))),
                              ],
                            ),
                          );
                          if (confirm != true) return;

                          setState(() => _isLoading = true);
                          try {
                            await ref
                                .read(appointmentRepositoryProvider)
                                .cancelMyAppointment(appointment.id);
                            ref.invalidate(myAppointmentsProvider);
                          } catch (error) {
                            if (mounted) {
                              ScaffoldMessenger.of(context).showSnackBar(
                                SnackBar(
                                  content: Text(
                                    UIErrorFormatter.getMessage(error),
                                  ),
                                  backgroundColor: Colors.red,
                                ),
                              );
                            }
                          } finally {
                            if (mounted) setState(() => _isLoading = false);
                          }
                        },
                        child: _isLoading
                            ? const SizedBox(
                                width: 16,
                                height: 16,
                                child:
                                    CircularProgressIndicator(strokeWidth: 2))
                            : Text("Cancel",
                                style:
                                    TextStyle(color: theme.colorScheme.error))),
                  if (isConfirmed) ...[
                    const SizedBox(width: 8),
                    Builder(builder: (context) {
                      final bool isOpen = appointment.isConsultationOpen;
                      final bool isClosed = appointment.isConsultationClosed;
                      final bool isLocked = appointment.isConsultationLocked;
                      final helperText = isClosed
                          ? 'Consultation closed'
                          : isLocked
                              ? 'Unlocks 10 min before start'
                              : 'Waiting for consultation window';
                      return Column(
                        crossAxisAlignment: CrossAxisAlignment.end,
                        children: [
                          Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              FilledButton.icon(
                                  onPressed: isOpen
                                      ? () => context.push('/chat', extra: {
                                            'title': appointment.doctorName,
                                            'isAi': false,
                                            'appointmentId': appointment.id,
                                            'doctorId': appointment.doctorId,
                                            'isCompleted': appointment.status ==
                                                'completed'
                                          })
                                      : null,
                                  icon: Icon(
                                    isOpen
                                        ? Icons.meeting_room
                                        : isClosed
                                            ? Icons.event_busy_outlined
                                            : Icons.lock_outline,
                                    size: 18,
                                  ),
                                  label: Text(isClosed
                                      ? "Consultation Closed"
                                      : "Join Consultation Room"),
                                  style: FilledButton.styleFrom(
                                    backgroundColor: isOpen
                                        ? theme.colorScheme.primary
                                        : Colors.grey.withOpacity(0.12),
                                    foregroundColor: isOpen
                                        ? theme.colorScheme.onPrimary
                                        : Colors.grey,
                                    elevation: 0,
                                  )),
                            ],
                          ),
                          if (!isOpen) ...[
                            const SizedBox(height: 4),
                            Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                Icon(
                                    isClosed
                                        ? Icons.event_busy_outlined
                                        : Icons.schedule,
                                    size: 12,
                                    color: Colors.grey.shade500),
                                const SizedBox(width: 4),
                                Text(
                                  helperText,
                                  style: TextStyle(
                                      fontSize: 11,
                                      color: Colors.grey.shade500),
                                ),
                              ],
                            ),
                          ],
                        ],
                      );
                    }),
                  ],
                  // â”€â”€ VIP: Doctor has proposed a time â†’ patient must pay â”€â”€â”€â”€â”€â”€
                  if (appointment.status == 'awaiting_payment') ...[
                    const SizedBox(width: 8),
                    // Cancel Request â€” patient rejects the proposed time
                    OutlinedButton(
                        onPressed: () async {
                          final confirm = await showDialog<bool>(
                            context: context,
                            builder: (ctx) => AlertDialog(
                              title: const Text("Cancel Request"),
                              content: const Text(
                                  "Are you sure you want to cancel this appointment request?"),
                              actions: [
                                TextButton(
                                    onPressed: () => Navigator.pop(ctx, false),
                                    child: const Text("Keep")),
                                TextButton(
                                    onPressed: () => Navigator.pop(ctx, true),
                                    child: const Text("Cancel",
                                        style: TextStyle(color: Colors.red))),
                              ],
                            ),
                          );
                          if (confirm != true) return;

                          setState(() => _isLoading = true);
                          try {
                            await ref
                                .read(appointmentRepositoryProvider)
                                .cancelMyAppointment(appointment.id);
                            if (context.mounted) {
                              ref.invalidate(myAppointmentsProvider);
                              ref.invalidate(nextAppointmentProvider);
                            }
                          } catch (e) {
                            if (context.mounted) {
                              ScaffoldMessenger.of(context).showSnackBar(
                                SnackBar(
                                  content: Text(UIErrorFormatter.getMessage(e)),
                                  backgroundColor: Colors.red,
                                ),
                              );
                            }
                          } finally {
                            if (mounted) setState(() => _isLoading = false);
                          }
                        },
                        style: OutlinedButton.styleFrom(
                          foregroundColor: theme.colorScheme.error,
                          side: BorderSide(
                              color: theme.colorScheme.error.withOpacity(0.5)),
                        ),
                        child: _isLoading
                            ? const SizedBox(
                                width: 16,
                                height: 16,
                                child:
                                    CircularProgressIndicator(strokeWidth: 2))
                            : const Text('Cancel Request')),
                  ],
                  if (canPatientPay) ...[
                    const SizedBox(width: 8),
                    ElevatedButton(
                        onPressed: () async {
                          await context.push('/payment', extra: {
                            'transactionType':
                                appointment.paymentTransactionType,
                            'baseAmount': appointment.amount,
                            'title': 'Consultation Payment',
                            'appointmentId': appointment.id,
                            'userId': appointment.patientId,
                            'paystackReference': appointment.paystackReference,
                          });
                          if (context.mounted) {
                            ref.invalidate(myAppointmentsProvider);
                            ref.invalidate(nextAppointmentProvider);
                          }
                        },
                        style: ElevatedButton.styleFrom(
                            backgroundColor: Colors.green,
                            foregroundColor: Colors.white),
                        child: const Text("Pay Now")),
                  ],
                  // â”€â”€ VIP pending: doctor hasn't proposed a time yet â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                  if (isVipRequest &&
                      appointment.status == 'pending' &&
                      isUnpaid) ...[
                    const SizedBox(width: 8),
                    Chip(
                      label: const Text(
                        'Awaiting Doctor\'s Proposal',
                        style: TextStyle(fontSize: 11),
                      ),
                      avatar: const Icon(Icons.hourglass_top, size: 14),
                      backgroundColor: Colors.grey.withOpacity(0.12),
                      labelStyle: TextStyle(color: Colors.grey.shade600),
                      side: BorderSide.none,
                    ),
                  ],
                  if (appointment.canPatientReportIssue) ...[
                    const SizedBox(width: 8),
                    OutlinedButton.icon(
                      onPressed: _isLoading ? null : _showComplaintDialog,
                      icon: const Icon(Icons.report_problem_outlined, size: 16),
                      label: const Text("Report Issue"),
                      style: OutlinedButton.styleFrom(
                        foregroundColor: theme.colorScheme.error,
                        side: BorderSide(color: theme.colorScheme.error),
                      ),
                    ),
                  ],
                  if (isCompleted && !appointment.hasReview) ...[
                    const SizedBox(width: 8),
                    ElevatedButton.icon(
                        onPressed: () => _showRatingSheet(context, ref),
                        icon: const Icon(Icons.star, size: 16),
                        label: const Text("Review"),
                        style: ElevatedButton.styleFrom(
                            backgroundColor: Colors.amber,
                            foregroundColor: Colors.black)),
                  ],
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}
