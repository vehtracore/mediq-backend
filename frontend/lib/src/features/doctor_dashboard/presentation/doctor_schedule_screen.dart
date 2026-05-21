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

class _AppointmentCard extends ConsumerStatefulWidget {
  final Appointment appointment;
  const _AppointmentCard({required this.appointment});

  @override
  ConsumerState<_AppointmentCard> createState() => _AppointmentCardState();
}

class _AppointmentCardState extends ConsumerState<_AppointmentCard> {

  void _showNotesDialog(BuildContext context) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text("Patient Notes"),
        content: Text(
          widget.appointment.notes != null && widget.appointment.notes!.isNotEmpty
              ? widget.appointment.notes!
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
                  .completeAppointment(widget.appointment.id);
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
                  .cancelMyAppointment(widget.appointment.id);
              if (context.mounted) ref.refresh(doctorScheduleProvider);
            },
            child: const Text("Cancel Appointment",
                style: TextStyle(color: Colors.red)),
          ),
        ],
      ),
    );
  }

  // ── NEW: Hospital Referral Dialog ──────────────────────────────────────────
  void _showReferralDialog(BuildContext context) {
    final hospitalCtrl = TextEditingController();
    final notesCtrl = TextEditingController();
    bool isSubmitting = false;

    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (ctx) {
        return StatefulBuilder(builder: (ctx, setDialogState) {
          return AlertDialog(
            shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(16)),
            title: const Row(
              children: [
                Icon(Icons.local_hospital_outlined,
                    color: Color(0xFFE53935), size: 22),
                SizedBox(width: 8),
                Text(
                  "Hospital Referral",
                  style: TextStyle(fontWeight: FontWeight.bold, fontSize: 18),
                ),
              ],
            ),
            content: SizedBox(
              width: double.maxFinite,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    "Referring: ${widget.appointment.patientName}",
                    style: const TextStyle(
                        fontSize: 13, color: Colors.grey),
                  ),
                  const SizedBox(height: 16),

                  // Hospital Name
                  const Text("Hospital Name",
                      style: TextStyle(
                          fontWeight: FontWeight.w600, fontSize: 13)),
                  const SizedBox(height: 6),
                  TextField(
                    controller: hospitalCtrl,
                    textCapitalization: TextCapitalization.words,
                    decoration: InputDecoration(
                      hintText: "e.g. Lagos Island General Hospital A\u0026E",
                      hintStyle: const TextStyle(
                          fontSize: 12, color: Colors.grey),
                      border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(10)),
                      contentPadding: const EdgeInsets.symmetric(
                          horizontal: 12, vertical: 10),
                    ),
                  ),
                  const SizedBox(height: 14),

                  // Clinical Notes
                  const Text("Clinical Notes",
                      style: TextStyle(
                          fontWeight: FontWeight.w600, fontSize: 13)),
                  const SizedBox(height: 6),
                  TextField(
                    controller: notesCtrl,
                    maxLines: 4,
                    textCapitalization: TextCapitalization.sentences,
                    decoration: InputDecoration(
                      hintText:
                          "Briefly describe the reason for referral and any relevant findings...",
                      hintStyle: const TextStyle(
                          fontSize: 12, color: Colors.grey),
                      border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(10)),
                      contentPadding: const EdgeInsets.symmetric(
                          horizontal: 12, vertical: 10),
                      alignLabelWithHint: true,
                    ),
                  ),
                ],
              ),
            ),
            actions: [
              TextButton(
                onPressed:
                    isSubmitting ? null : () => Navigator.pop(ctx),
                child: const Text("Cancel"),
              ),
              ElevatedButton.icon(
                onPressed: isSubmitting
                    ? null
                    : () async {
                        final hospital = hospitalCtrl.text.trim();
                        final note = notesCtrl.text.trim();
                        if (hospital.isEmpty || note.isEmpty) {
                          ScaffoldMessenger.of(context).showSnackBar(
                            const SnackBar(
                                content: Text(
                                    "Please fill in both fields."),
                                backgroundColor: Colors.orange),
                          );
                          return;
                        }
                        setDialogState(() => isSubmitting = true);
                        try {
                          await ref
                              .read(appointmentRepositoryProvider)
                              .referAppointment(
                                id: widget.appointment.id,
                                hospitalName: hospital,
                                note: note,
                              );
                          if (ctx.mounted) Navigator.pop(ctx);
                          if (context.mounted) {
                            ref.refresh(doctorScheduleProvider);
                            ScaffoldMessenger.of(context).showSnackBar(
                              SnackBar(
                                content: Text(
                                    "✅ ${widget.appointment.patientName} referred to $hospital."),
                                backgroundColor: Colors.green,
                                duration: const Duration(seconds: 4),
                              ),
                            );
                          }
                        } catch (e) {
                          setDialogState(() => isSubmitting = false);
                          if (context.mounted) {
                            ScaffoldMessenger.of(context).showSnackBar(
                              SnackBar(
                                content: Text(e.toString()),
                                backgroundColor: Colors.red,
                              ),
                            );
                          }
                        }
                      },
                style: ElevatedButton.styleFrom(
                  backgroundColor: const Color(0xFFE53935),
                  foregroundColor: Colors.white,
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(10)),
                ),
                icon: isSubmitting
                    ? const SizedBox(
                        width: 14,
                        height: 14,
                        child: CircularProgressIndicator(
                            color: Colors.white, strokeWidth: 2))
                    : const Icon(Icons.send_outlined, size: 16),
                label: Text(isSubmitting ? "Submitting..." : "Submit Referral"),
              ),
            ],
          );
        });
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final timeStr = DateFormat('jm').format(widget.appointment.startTime);
    String timeNum = timeStr.split(' ')[0];
    String timeAmPm = timeStr.contains(' ') ? timeStr.split(' ')[1] : "";
    final theme = Theme.of(context);
    
    final isConfirmed = widget.appointment.status == 'confirmed';
    final isCompleted = widget.appointment.status == 'completed';

    Color statusBgColor = Colors.orange.withOpacity(0.1);
    Color statusTextColor = Colors.orange;
    if (isConfirmed) {
      statusBgColor = Colors.green.withOpacity(0.1);
      statusTextColor = Colors.green;
    } else if (isCompleted) {
      statusBgColor = Colors.blue.withOpacity(0.1);
      statusTextColor = Colors.blue;
    } else if (widget.appointment.status == 'cancelled') {
      statusBgColor = Colors.grey.shade200;
      statusTextColor = Colors.grey.shade700;
    }

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: theme.cardTheme.color,
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
                      widget.appointment.patientName,
                      style: theme.textTheme.titleLarge?.copyWith(
                        fontWeight: FontWeight.bold,
                        fontSize: 18,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Row(
                      children: [
                        Icon(Icons.calendar_today,
                            size: 14,
                            color: theme.iconTheme.color?.withOpacity(0.7)),
                        const SizedBox(width: 4),
                        Text(
                          DateFormat('MMM dd').format(widget.appointment.startTime),
                          style: theme.textTheme.bodyMedium
                              ?.copyWith(fontSize: 13),
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 8, vertical: 4),
                      decoration: BoxDecoration(
                          color: statusBgColor,
                          borderRadius: BorderRadius.circular(8)),
                      child: Text(widget.appointment.status.toUpperCase(),
                          style: TextStyle(
                              color: statusTextColor,
                              fontSize: 10,
                              fontWeight: FontWeight.bold)),
                    ),
                  ],
                ),
              ),
              PopupMenuButton<String>(
                onSelected: (value) {
                  if (value == 'notes') {
                    _showNotesDialog(context);
                  } else if (value == 'refer') {
                    _showReferralDialog(context);
                  } else if (value == 'complete') {
                    _confirmCompletion(context, ref);
                  } else if (value == 'cancel') {
                    _confirmCancellation(context, ref);
                  }
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
                  PopupMenuItem<String>(
                    value: 'refer',
                    child: Row(children: [
                      Icon(Icons.local_hospital_outlined, color: theme.colorScheme.primary),
                      const SizedBox(width: 8),
                      Text('Refer Patient', 
                          style: theme.textTheme.bodyMedium?.copyWith(
                            color: theme.colorScheme.primary,
                            fontWeight: FontWeight.w600,
                          ))
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
          if (widget.appointment.status != 'cancelled' && isConfirmed)
            FittedBox(
              fit: BoxFit.scaleDown,
              child: Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  IconButton.filledTonal(
                      onPressed: () => context.push('/chat', extra: {
                            'title': widget.appointment.patientName,
                            'isAi': false,
                            'appointmentId': widget.appointment.id,
                            'isCompleted': widget.appointment.status == 'completed'
                          }),
                      icon: const Icon(Icons.chat_bubble_outline, size: 18),
                      style: IconButton.styleFrom(
                          backgroundColor: theme.colorScheme.primary.withOpacity(0.15),
                          foregroundColor: theme.colorScheme.primary,
                      )),
                  const SizedBox(width: 8),
                  IconButton.filledTonal(
                      onPressed: () => context.push('/video_call?type=voice',
                          extra: widget.appointment.id),
                      icon: const Icon(Icons.phone, size: 18),
                      style: IconButton.styleFrom(
                          backgroundColor: theme.colorScheme.primary.withOpacity(0.15),
                          foregroundColor: theme.colorScheme.primary,
                      )),
                  const SizedBox(width: 8),
                  FilledButton.tonalIcon(
                      onPressed: () =>
                          context.push('/video_call', extra: widget.appointment.id),
                      icon: const Icon(Icons.videocam, size: 16),
                      label: const Text("Video"),
                      style: FilledButton.styleFrom(
                          backgroundColor: theme.colorScheme.primary.withOpacity(0.15),
                          foregroundColor: theme.colorScheme.primary,
                          elevation: 0,
                      )),
                ],
              ),
            ),
        ],
      ),
    );
  }
}
