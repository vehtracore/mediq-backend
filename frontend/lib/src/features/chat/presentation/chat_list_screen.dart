import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';
import '../../appointments/data/appointment_model.dart';
import '../../appointments/data/appointment_repository.dart';
import 'package:mediq_app/presentation/widgets/global_error_widget.dart';

/// Purpose: Drives the state of the user's Chat list screen by fetching their appointments
/// and strictly filtering for 'confirmed' status, which governs access to active doctor communication channels.
///
/// Data Source: Communicates with `appointmentRepositoryProvider` (`getMyAppointments()` API endpoint).
///
/// Invalidation Strategy: Should be explicitly invalidated via `ref.invalidate(chatAppointmentsProvider)` 
/// on pull-to-refresh, retry taps in GlobalErrorWidget, or post-booking/status-change mutations.
///
/// Error & Loading Annotations: Exceptions thrown by the API (like `DioException`) are caught by Riverpod 
/// and translated into clean localized strings by the `GlobalErrorWidget` wrapped around this provider's `error` state.
final chatAppointmentsProvider =
    FutureProvider.autoDispose<List<Appointment>>((ref) async {
  final repo = ref.watch(appointmentRepositoryProvider);
  final allAppointments = await repo.getMyAppointments();
  return allAppointments.where((a) => a.status == 'confirmed').toList();
});

class ChatListScreen extends ConsumerWidget {
  const ChatListScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final appointmentsAsync = ref.watch(chatAppointmentsProvider);
    final theme = Theme.of(context);

    return Scaffold(
      backgroundColor: theme.scaffoldBackgroundColor, // ✅ Dynamic
      appBar: AppBar(
        title: Text("Messages", style: theme.textTheme.titleLarge),
        backgroundColor: theme.appBarTheme.backgroundColor,
        elevation: 0,
        centerTitle: false,
        automaticallyImplyLeading: false,
      ),
      body: appointmentsAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (err, stack) => GlobalErrorWidget(
              error: err,
              onRetry: () => ref.invalidate(chatAppointmentsProvider),
            ),
        data: (appointments) {
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              _ChatTile(
                name: "Health Assistant",
                subtitle: "Click to check symptoms",
                time: "Now",
                isAi: true,
                onTap: () => context.push('/chat', extra: {'isAi': true}),
              ),
              const SizedBox(height: 24),
              const Padding(
                padding: EdgeInsets.only(left: 8, bottom: 8),
                child: Text("Doctor Consultations",
                    style: TextStyle(
                        fontWeight: FontWeight.bold, color: Colors.grey)),
              ),
              if (appointments.isEmpty)
                _buildEmptyState(theme)
              else
                ...appointments
                    .map((appt) => _DoctorChatTile(appointment: appt)),
            ],
          );
        },
      ),
    );
  }

  Widget _buildEmptyState(ThemeData theme) {
    return Container(
      padding: const EdgeInsets.all(24),
      alignment: Alignment.center,
      child: Column(children: [
        Icon(Icons.chat_bubble_outline, size: 48, color: Colors.grey[300]),
        const SizedBox(height: 12),
        Text("No upcoming consultations.",
            style: TextStyle(color: Colors.grey[500])),
      ]),
    );
  }
}

class _ChatTile extends StatelessWidget {
  final String name, subtitle, time;
  final bool isAi;
  final VoidCallback onTap;
  const _ChatTile(
      {required this.name,
      required this.subtitle,
      required this.time,
      this.isAi = false,
      required this.onTap});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      decoration: BoxDecoration(
          color: theme.cardTheme.color, // ✅ Dynamic
          borderRadius: BorderRadius.circular(16),
          boxShadow: theme.brightness == Brightness.dark
              ? []
              : [
                  BoxShadow(
                      color: Colors.grey.withOpacity(0.05),
                      blurRadius: 10,
                      offset: const Offset(0, 4))
                ]),
      child: ListTile(
        onTap: onTap,
        contentPadding: const EdgeInsets.all(12),
        leading: Container(
            width: 50,
            height: 50,
            decoration: BoxDecoration(
                color: const Color(0xFF4A90E2).withOpacity(0.1),
                shape: BoxShape.circle),
            child:
                const Icon(Icons.smart_toy_outlined, color: Color(0xFF4A90E2))),
        title: Text(name,
            style: theme.textTheme.bodyLarge
                ?.copyWith(fontWeight: FontWeight.bold)),
        subtitle: Text(subtitle,
            style: const TextStyle(color: Color(0xFF4A90E2), fontSize: 12)),
        trailing:
            Text(time, style: TextStyle(color: Colors.grey[400], fontSize: 12)),
      ),
    );
  }
}

class _DoctorChatTile extends StatelessWidget {
  final Appointment appointment;
  const _DoctorChatTile({required this.appointment});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final now = DateTime.now();
    final unlockTime =
        appointment.startTime != null ? appointment.startTime!.subtract(const Duration(minutes: 10)) : DateTime(2099);
    final isUnlocked = now.isAfter(unlockTime);
    final timeStr = appointment.startTime != null ? DateFormat('MMM dd, h:mm a').format(appointment.startTime!) : 'Pending';

    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(
          color: theme.cardTheme.color, // ✅ Dynamic
          borderRadius: BorderRadius.circular(16),
          boxShadow: theme.brightness == Brightness.dark
              ? []
              : [
                  BoxShadow(
                      color: Colors.grey.withOpacity(0.05),
                      blurRadius: 10,
                      offset: const Offset(0, 4))
                ]),
      child: ListTile(
        contentPadding: const EdgeInsets.all(12),
        onTap: () {
          if (isUnlocked) {
            context.push('/chat',
                extra: {
                  'title': appointment.doctorName,
                  'isAi': false,
                  'appointmentId': appointment.id,
                  'doctorId': appointment.doctorId,
                  'isCompleted': appointment.status == 'completed',
                });
          } else {
            ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                content: Text("Chat opens 10 minutes before appointment."),
                backgroundColor: Colors.orange));
          }
        },
        leading: CircleAvatar(
            radius: 25,
            backgroundColor: isUnlocked ? Colors.blue : Colors.grey[200],
            child: Text(
                appointment.doctorName.isNotEmpty
                    ? appointment.doctorName[0]
                    : "D",
                style: TextStyle(
                    color: isUnlocked ? Colors.white : Colors.black))),
        title: Text(appointment.doctorName,
            style: theme.textTheme.bodyLarge
                ?.copyWith(fontWeight: FontWeight.bold)),
        subtitle: Text("Consultation at $timeStr",
            style: TextStyle(color: Colors.grey[600], fontSize: 12)),
        trailing: Icon(isUnlocked ? Icons.videocam : Icons.lock_outline,
            color: isUnlocked ? Colors.green : Colors.grey),
      ),
    );
  }
}
