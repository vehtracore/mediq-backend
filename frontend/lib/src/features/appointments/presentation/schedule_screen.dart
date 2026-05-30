import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';
import 'package:mediq_app/src/features/reviews/data/review_repository.dart';
import 'package:mediq_app/src/features/patient_dashboard/presentation/widgets/home_widgets.dart';
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
    // Is it in the future? Keep it.
    if (appt.startTime != null && appt.startTime!.isAfter(now)) return true;

    // Is it active/unfinished? Keep it.
    // 'awaiting_payment' = VIP where doctor proposed a time but patient hasn't paid yet.
    if (appt.status == 'pending' ||
        appt.status == 'confirmed' ||
        appt.status == 'awaiting_payment') return true;

    // Is it a recent history item (less than 30 days old)? Keep it.
    if (appt.startTime != null && appt.startTime!.isAfter(thirtyDaysAgo)) return true;

    // Otherwise, hide it.
    return false;
  }).toList();

  // Sort by date (Newest at the top)
  filtered.sort((a, b) => (b.startTime ?? DateTime(2099)).compareTo(a.startTime ?? DateTime(2099)));

  return filtered;
});

class ScheduleScreen extends ConsumerWidget {
  const ScheduleScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final appointmentsAsync = ref.watch(myAppointmentsProvider);
    final theme = Theme.of(context);

    return Scaffold(
      backgroundColor: theme.scaffoldBackgroundColor, // ✅ Dynamic
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
            return const Center(child: Text("No appointments yet"));
          }
          return ListView.separated(
            padding: const EdgeInsets.all(16),
            itemCount: appointments.length,
            separatorBuilder: (_, __) => const SizedBox(height: 16),
            itemBuilder: (context, index) =>
                _AppointmentCard(appointment: appointments[index]),
          );
        },
      ),
    );
  }
}

class _AppointmentCard extends ConsumerWidget {
  final Appointment appointment;
  const _AppointmentCard({required this.appointment});

  void _showRatingSheet(BuildContext context, WidgetRef ref) {
    int selectedRating = 5;
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
                      onPressed: () async {
                        Navigator.pop(ctx);
                        try {
                          await ref.read(reviewRepositoryProvider).submitReview(
                              appointmentId: appointment.id,
                              rating: selectedRating,
                              comment: commentCtrl.text);
                          ref.refresh(myAppointmentsProvider);
                        } catch (e) {}
                      },
                      style: ElevatedButton.styleFrom(
                          backgroundColor: const Color(0xFF4A90E2),
                          foregroundColor: Colors.white),
                      child: const Text("Submit Review"))),
              const SizedBox(height: 24),
            ],
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;

    final dayMonth = appointment.startTime != null ? DateFormat('MMM dd').format(appointment.startTime!) : 'Pending Date';
    final time = appointment.startTime != null ? DateFormat('jm').format(appointment.startTime!) : 'Pending Time';
    final isConfirmed = appointment.status == 'confirmed';
    final isCompleted = appointment.status == 'completed';
    final isUnpaid = appointment.paymentStatus == 'unpaid';

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
    // VIP: doctor proposed a time, patient needs to pay
    if (appointment.status == 'awaiting_payment') {
      statusBgColor = const Color(0xFF7C3AED).withOpacity(0.1);
      statusTextColor = const Color(0xFF7C3AED);
    }

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: theme.cardTheme.color, // ✅ Dynamic Card
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
                          style: const TextStyle(fontSize: 12, color: Colors.grey)),
                      const SizedBox(height: 4),
                      Text(appointment.doctorName,
                          style: theme.textTheme.titleMedium
                              ?.copyWith(fontWeight: FontWeight.bold)),
                      const SizedBox(height: 8),
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 8, vertical: 4),
                        decoration: BoxDecoration(
                            color: statusBgColor,
                            borderRadius: BorderRadius.circular(8)),
                        child: Text(appointment.status.toUpperCase(),
                            style: TextStyle(
                                color: statusTextColor,
                                fontSize: 10,
                                fontWeight: FontWeight.bold)),
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
                  if (appointment.status == 'pending' || isConfirmed)
                    TextButton(
                        onPressed: () async {
                          final confirm = await showDialog<bool>(
                            context: context,
                            builder: (ctx) => AlertDialog(
                              title: const Text("Cancel Consultation"),
                              content: const Text("Are you sure you want to cancel this consultation?"),
                              actions: [
                                TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text("Keep")),
                                TextButton(onPressed: () => Navigator.pop(ctx, true), child: const Text("Cancel", style: TextStyle(color: Colors.red))),
                              ],
                            ),
                          );
                          if (confirm != true) return;
                          
                          try {
                            await ref
                                .read(appointmentRepositoryProvider)
                                .cancelMyAppointment(appointment.id);
                            ref.refresh(myAppointmentsProvider);
                          } catch (e) {}
                        },
                        child: Text("Cancel",
                            style: TextStyle(color: theme.colorScheme.error))),
                  if (isConfirmed) ...[
                    const SizedBox(width: 8),
                    Builder(builder: (context) {
                      final st = appointment.startTime;
                      final bool isUnlocked = st == null ||
                          DateTime.now().isAfter(
                              st.subtract(const Duration(minutes: 10)));
                      return Column(
                        crossAxisAlignment: CrossAxisAlignment.end,
                        children: [
                          Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              IconButton.filledTonal(
                                  onPressed: isUnlocked
                                      ? () => context.push('/chat', extra: {
                                            'title': appointment.doctorName,
                                            'isAi': false,
                                            'appointmentId': appointment.id,
                                            'doctorId': appointment.doctorId,
                                            'isCompleted': appointment.status == 'completed'
                                          })
                                      : null,
                                  icon: Icon(
                                    isUnlocked
                                        ? Icons.chat_bubble_outline
                                        : Icons.lock_outline,
                                    size: 18,
                                  ),
                                  style: IconButton.styleFrom(
                                      backgroundColor: isUnlocked
                                          ? theme.colorScheme.primary.withOpacity(0.15)
                                          : Colors.grey.withOpacity(0.12),
                                      foregroundColor: isUnlocked
                                          ? theme.colorScheme.primary
                                          : Colors.grey,
                                  )),
                              const SizedBox(width: 8),
                              IconButton.filledTonal(
                                  onPressed: isUnlocked
                                      ? () => context.push('/video_call?type=voice',
                                          extra: appointment.id)
                                      : null,
                                  icon: Icon(
                                    isUnlocked
                                        ? Icons.phone
                                        : Icons.lock_outline,
                                    size: 18,
                                  ),
                                  style: IconButton.styleFrom(
                                      backgroundColor: isUnlocked
                                          ? theme.colorScheme.primary.withOpacity(0.15)
                                          : Colors.grey.withOpacity(0.12),
                                      foregroundColor: isUnlocked
                                          ? theme.colorScheme.primary
                                          : Colors.grey,
                                  )),
                              const SizedBox(width: 8),
                              FilledButton.tonalIcon(
                                  onPressed: isUnlocked
                                      ? () => context.push(
                                          '/video_call', extra: appointment.id)
                                      : null,
                                  icon: Icon(
                                    isUnlocked
                                        ? Icons.videocam
                                        : Icons.lock_outline,
                                    size: 16,
                                  ),
                                  label: const Text("Video"),
                                  style: FilledButton.styleFrom(
                                      backgroundColor: isUnlocked
                                          ? theme.colorScheme.primary.withOpacity(0.15)
                                          : Colors.grey.withOpacity(0.12),
                                      foregroundColor: isUnlocked
                                          ? theme.colorScheme.primary
                                          : Colors.grey,
                                      elevation: 0,
                                  )),
                            ],
                          ),
                          if (!isUnlocked) ...[
                            const SizedBox(height: 4),
                            Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                Icon(Icons.schedule,
                                    size: 12, color: Colors.grey.shade500),
                                const SizedBox(width: 4),
                                Text(
                                  'Unlocks 10 min before start',
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
                  // ── VIP: Doctor has proposed a time → patient must pay ──────
                  if (appointment.status == 'awaiting_payment') ...[
                    const SizedBox(width: 8),
                    // Cancel Request — patient rejects the proposed time
                    OutlinedButton(
                        onPressed: () async {
                          final confirm = await showDialog<bool>(
                            context: context,
                            builder: (ctx) => AlertDialog(
                              title: const Text("Cancel Request"),
                              content: const Text("Are you sure you want to cancel this appointment request?"),
                              actions: [
                                TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text("Keep")),
                                TextButton(onPressed: () => Navigator.pop(ctx, true), child: const Text("Cancel", style: TextStyle(color: Colors.red))),
                              ],
                            ),
                          );
                          if (confirm != true) return;

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
                                  content: Text('Could not cancel: $e'),
                                  backgroundColor: Colors.red,
                                ),
                              );
                            }
                          }
                        },
                        style: OutlinedButton.styleFrom(
                            foregroundColor: theme.colorScheme.error,
                            side: BorderSide(
                                color: theme.colorScheme.error.withOpacity(0.5)),
                        ),
                        child: const Text('Cancel Request')),
                    const SizedBox(width: 8),
                    ElevatedButton(
                        onPressed: () async {
                          final result = await context.push('/payment', extra: {
                            'transactionType': 'specialist_consult',
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
                  // ── VIP pending: doctor hasn't proposed a time yet ──────────
                  if (appointment.status == 'pending' && isUnpaid) ...[
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
