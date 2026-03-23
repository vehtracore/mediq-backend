import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:go_router/go_router.dart';
import '../../appointments/data/appointment_model.dart';
import '../../appointments/data/appointment_repository.dart';

final doctorScheduleProvider = FutureProvider.autoDispose<List<Appointment>>((
  ref,
) async {
  final repo = ref.watch(appointmentRepositoryProvider);
  return await repo.getDoctorConfirmedAppointments();
});

class DoctorScheduleScreen extends ConsumerWidget {
  const DoctorScheduleScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final scheduleAsync = ref.watch(doctorScheduleProvider);
    final theme = Theme.of(context);

    return Scaffold(
      backgroundColor: theme.scaffoldBackgroundColor, // ✅ Dynamic Background
      body: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 24, 24, 16),
              child: Text(
                "My Schedule",
                style: theme.textTheme.headlineMedium?.copyWith(
                  fontWeight: FontWeight.bold,
                  // Remove hardcoded color, let theme handle it
                ),
              ),
            ),
            Expanded(
              child: scheduleAsync.when(
                loading: () => const Center(child: CircularProgressIndicator()),
                error: (err, stack) => Center(child: Text("Error: $err")),
                data: (appointments) {
                  if (appointments.isEmpty) {
                    return const Center(
                      child: Text("No upcoming appointments"),
                    );
                  }
                  return ListView.separated(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 24,
                      vertical: 8,
                    ),
                    itemCount: appointments.length,
                    separatorBuilder: (_, __) => const SizedBox(height: 16),
                    itemBuilder: (context, index) =>
                        _AppointmentCard(appointment: appointments[index]),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _AppointmentCard extends ConsumerWidget {
  final Appointment appointment;
  const _AppointmentCard({required this.appointment});

  // ... (Keep existing dialog methods: _showNotesDialog, _confirmCompletion, _confirmCancellation) ...
  // Re-paste them from your previous file if needed, or simply replace the `build` method below.
  // To be safe, I will include the dialog helpers to ensure they work with dark mode text.

  void _showNotesDialog(BuildContext context) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text("Patient Notes"),
        content: Text(
          appointment.notes != null && appointment.notes!.isNotEmpty
              ? appointment.notes!
              : "No notes provided.",
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text("Close"),
          ),
        ],
      ),
    );
  }

  void _confirmCompletion(BuildContext context, WidgetRef ref) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text("Complete Consultation?"),
        content: const Text("This will mark the session as finished."),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx), child: const Text("Cancel")),
          TextButton(
            onPressed: () async {
              Navigator.pop(ctx);
              await ref
                  .read(appointmentRepositoryProvider)
                  .completeAppointment(appointment.id);
              if (context.mounted) ref.refresh(doctorScheduleProvider);
            },
            child: const Text("Confirm", style: TextStyle(color: Colors.green)),
          ),
        ],
      ),
    );
  }

  void _confirmCancellation(BuildContext context, WidgetRef ref) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text("Cancel Appointment?"),
        content: const Text("This cannot be undone."),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx), child: const Text("Back")),
          TextButton(
            onPressed: () async {
              Navigator.pop(ctx);
              await ref
                  .read(appointmentRepositoryProvider)
                  .cancelMyAppointment(appointment.id);
              if (context.mounted) ref.refresh(doctorScheduleProvider);
            },
            child: const Text("Cancel Appointment",
                style: TextStyle(color: Colors.red)),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final timeStr = DateFormat('jm').format(appointment.startTime);
    String timeNum = timeStr.split(' ')[0];
    String timeAmPm = timeStr.contains(' ') ? timeStr.split(' ')[1] : "";
    final theme = Theme.of(context);

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: theme.cardTheme.color, // ✅ Dynamic Background
        borderRadius: BorderRadius.circular(16),
        boxShadow: theme.brightness == Brightness.dark
            ? []
            : [BoxShadow(color: Colors.grey.withOpacity(0.08), blurRadius: 10)],
      ),
      child: Column(
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 8,
                ),
                decoration: BoxDecoration(
                  color: const Color(0xFF4A90E2).withOpacity(0.1),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Column(
                  children: [
                    Text(
                      timeNum,
                      style: const TextStyle(
                        fontWeight: FontWeight.bold,
                        color: Color(0xFF4A90E2),
                        fontSize: 16,
                      ),
                    ),
                    if (timeAmPm.isNotEmpty)
                      Text(
                        timeAmPm,
                        style: const TextStyle(
                          fontSize: 12,
                          color: Color(0xFF4A90E2),
                        ),
                      ),
                  ],
                ),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      appointment.patientName,
                      style: theme.textTheme.titleLarge?.copyWith(
                        fontWeight: FontWeight.bold,
                        fontSize: 18,
                      ), // ✅ Dynamic Text
                    ),
                    const SizedBox(height: 4),
                    Row(
                      children: [
                        Icon(Icons.calendar_today,
                            size: 14,
                            color: theme.iconTheme.color?.withOpacity(0.7)),
                        const SizedBox(width: 4),
                        Text(
                          DateFormat('MMM dd').format(appointment.startTime),
                          style: theme.textTheme.bodyMedium
                              ?.copyWith(fontSize: 13), // ✅ Dynamic
                        ),
                        const SizedBox(width: 12),
                        const Icon(Icons.payment,
                            size: 14, color: Colors.green),
                        const SizedBox(width: 4),
                        Text(
                          appointment.paymentStatus.toUpperCase(),
                          style: const TextStyle(
                            color: Colors.green,
                            fontSize: 12,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),

              // --- 3-DOT MENU ---
              PopupMenuButton<String>(
                onSelected: (value) {
                  if (value == 'notes')
                    _showNotesDialog(context);
                  else if (value == 'complete')
                    _confirmCompletion(context, ref);
                  else if (value == 'cancel')
                    _confirmCancellation(context, ref);
                },
                color: theme.cardTheme.color, // ✅ Dynamic Menu Background
                itemBuilder: (BuildContext context) => <PopupMenuEntry<String>>[
                  PopupMenuItem<String>(
                    value: 'notes',
                    child: Row(children: [
                      Icon(Icons.notes, color: theme.iconTheme.color),
                      const SizedBox(width: 8),
                      Text('View Notes', style: theme.textTheme.bodyMedium)
                    ]),
                  ),
                  const PopupMenuItem<String>(
                    value: 'complete',
                    child: Row(children: [
                      Icon(Icons.check_circle_outline, color: Colors.green),
                      SizedBox(width: 8),
                      Text('Mark Complete',
                          style: TextStyle(color: Colors.green))
                    ]),
                  ),
                  const PopupMenuDivider(),
                  const PopupMenuItem<String>(
                    value: 'cancel',
                    child: Row(children: [
                      Icon(Icons.cancel_outlined, color: Colors.red),
                      SizedBox(width: 8),
                      Text('Cancel', style: TextStyle(color: Colors.red))
                    ]),
                  ),
                ],
                icon: Icon(Icons.more_vert, color: theme.iconTheme.color),
              ),
            ],
          ),
          const SizedBox(height: 16),

          // Action Buttons
          Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: () => context.push('/chat', extra: {
                    'title': appointment.patientName,
                    'appointmentId': appointment.id,
                    'isCompleted': appointment.status == 'completed'
                  }),
                  icon: const Icon(Icons.chat_bubble_outline, size: 16),
                  label: const Text("Chat"),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: Colors.blue,
                    side: const BorderSide(color: Colors.blue),
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                flex: 2,
                child: ElevatedButton.icon(
                  onPressed: () =>
                      context.push('/video_call', extra: appointment.id),
                  icon: const Icon(Icons.videocam_outlined),
                  label: const Text("Start Call"),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF4A90E2),
                    foregroundColor: Colors.white,
                    shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12)),
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
