import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:mediq_app/src/features/appointments/data/appointment_repository.dart';

// Provider that generates notifications based on real appointments
final notificationsProvider =
    FutureProvider.autoDispose<List<Map<String, dynamic>>>((ref) async {
  final repo = ref.watch(appointmentRepositoryProvider);
  final appointments = await repo.getMyAppointments();

  final List<Map<String, dynamic>> notifs = [];

  // 1. Generate appointment alerts
  for (var appt in appointments) {
    if (appt.status == 'confirmed') {
      notifs.add({
        'title': 'Upcoming Appointment',
        'body':
            'You have a session with ${appt.doctorName} at ${DateFormat('h:mm a').format(appt.startTime)}.',
        'time': DateFormat('MMM d').format(appt.startTime),
        'icon': Icons.calendar_today,
        'color': Colors.blue,
      });
    } else if (appt.status == 'cancelled') {
      notifs.add({
        'title': 'Appointment Cancelled',
        'body': 'Your session with ${appt.doctorName} was cancelled.',
        'time': DateFormat('MMM d').format(appt.startTime),
        'icon': Icons.cancel,
        'color': Colors.red,
      });
    }
  }

  // 2. Add generic system messages
  notifs.add({
    'title': 'Welcome to MDQ+',
    'body': 'Complete your profile to get better AI health tips.',
    'time': 'Just now',
    'icon': Icons.star,
    'color': Colors.amber,
  });

  return notifs;
});

class NotificationsScreen extends ConsumerWidget {
  const NotificationsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final notifsAsync = ref.watch(notificationsProvider);
    final theme = Theme.of(context);

    return Scaffold(
      backgroundColor: theme.scaffoldBackgroundColor,
      appBar: AppBar(
        title: Text("Notifications", style: theme.textTheme.titleLarge),
        backgroundColor: theme.appBarTheme.backgroundColor,
        elevation: 0,
      ),
      body: notifsAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text("Error loading notifications")),
        data: (notifications) {
          if (notifications.isEmpty) {
            return Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(Icons.notifications_off_outlined,
                      size: 64, color: Colors.grey[300]),
                  const SizedBox(height: 16),
                  Text("No new notifications",
                      style: TextStyle(color: Colors.grey[600], fontSize: 16)),
                ],
              ),
            );
          }
          return ListView.separated(
            padding: const EdgeInsets.all(16),
            itemCount: notifications.length,
            separatorBuilder: (_, __) => const SizedBox(height: 12),
            itemBuilder: (context, index) {
              final item = notifications[index];
              return Container(
                decoration: BoxDecoration(
                  color: theme.cardTheme.color,
                  borderRadius: BorderRadius.circular(12),
                  boxShadow: [
                    BoxShadow(
                        color: Colors.grey.withOpacity(0.05),
                        blurRadius: 8,
                        offset: const Offset(0, 2))
                  ],
                ),
                child: ListTile(
                  contentPadding:
                      const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                  leading: CircleAvatar(
                    backgroundColor: (item['color'] as Color).withOpacity(0.1),
                    child: Icon(item['icon'] as IconData, color: item['color']),
                  ),
                  title: Text(item['title'],
                      style: theme.textTheme.bodyLarge
                          ?.copyWith(fontWeight: FontWeight.bold)),
                  subtitle: Padding(
                    padding: const EdgeInsets.only(top: 4.0),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(item['body'], style: theme.textTheme.bodyMedium),
                        const SizedBox(height: 6),
                        Text(item['time'],
                            style: TextStyle(
                                fontSize: 12, color: Colors.grey[500])),
                      ],
                    ),
                  ),
                ),
              );
            },
          );
        },
      ),
    );
  }
}
