import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:mediq_app/src/features/appointments/data/appointment_repository.dart';

// ✅ Logic Refined: Generates alerts based on Appointments + System Tips
final notificationsProvider =
    FutureProvider.autoDispose<List<Map<String, dynamic>>>((ref) async {
  final repo = ref.watch(appointmentRepositoryProvider);
  
  // Fetch latest appointments
  final appointments = await repo.getMyAppointments();

  final List<Map<String, dynamic>> notifs = [];

  // 1. Generate Appointment Alerts (Dynamic)
  // Sort by most recent first
  appointments.sort((a, b) => b.startTime.compareTo(a.startTime));

  for (var appt in appointments) {
    if (appt.status == 'confirmed') {
      notifs.add({
        'id': 'appt_${appt.id}',
        'title': 'Appointment Confirmed',
        'body': 'Session with ${appt.doctorName} at ${DateFormat('h:mm a').format(appt.startTime)}.',
        'time': DateFormat('MMM d').format(appt.startTime),
        'icon': Icons.calendar_check,
        'color': Colors.blue,
        'is_system': false,
      });
    } else if (appt.status == 'cancelled') {
      notifs.add({
        'id': 'appt_${appt.id}_cancel',
        'title': 'Appointment Cancelled',
        'body': 'Your session with ${appt.doctorName} was cancelled.',
        'time': DateFormat('MMM d').format(appt.startTime),
        'icon': Icons.cancel_presentation,
        'color': Colors.red,
        'is_system': false,
      });
    }
  }

  // 2. Add System Messages (Pinned at bottom or top)
  notifs.add({
    'id': 'sys_welcome',
    'title': 'Welcome to MDQ+',
    'body': 'Complete your medical profile to get accurate AI health tips.',
    'time': 'Tip',
    'icon': Icons.verified_user,
    'color': Colors.amber,
    'is_system': true,
  });

  return notifs;
});

class NotificationsScreen extends ConsumerWidget {
  const NotificationsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final notifsAsync = ref.watch(notificationsProvider);
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;

    return Scaffold(
      backgroundColor: theme.scaffoldBackgroundColor,
      appBar: AppBar(
        title: Text("Notifications", style: theme.textTheme.titleLarge),
        backgroundColor: theme.appBarTheme.backgroundColor,
        elevation: 0,
        centerTitle: false,
      ),
      body: notifsAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(Icons.error_outline, size: 48, color: Colors.red),
              const SizedBox(height: 16),
              Text("Couldn't load notifications", style: theme.textTheme.bodyLarge),
              TextButton(
                onPressed: () => ref.refresh(notificationsProvider), 
                child: const Text("Retry"),
              )
            ],
          ),
        ),
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

          // ✅ Added RefreshIndicator for Pull-to-Refresh
          return RefreshIndicator(
            onRefresh: () async => ref.refresh(notificationsProvider),
            child: ListView.separated(
              padding: const EdgeInsets.all(16),
              itemCount: notifications.length,
              separatorBuilder: (_, __) => const SizedBox(height: 12),
              itemBuilder: (context, index) {
                final item = notifications[index];
                return _buildNotificationItem(context, item, theme, isDark);
              },
            ),
          );
        },
      ),
    );
  }

  Widget _buildNotificationItem(BuildContext context, Map<String, dynamic> item, ThemeData theme, bool isDark) {
    final Color itemColor = item['color'];
    
    return Container(
      decoration: BoxDecoration(
        color: theme.cardTheme.color,
        borderRadius: BorderRadius.circular(16), // Softer corners
        boxShadow: isDark
            ? []
            : [
                BoxShadow(
                    color: Colors.grey.withOpacity(0.05),
                    blurRadius: 10,
                    offset: const Offset(0, 4))
              ],
      ),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(16),
          onTap: () {
            // Future: Navigate to Appointment details if it's an appointment
          },
          child: Padding(
            padding: const EdgeInsets.all(16.0),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Icon Box
                Container(
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: itemColor.withOpacity(0.1),
                    shape: BoxShape.circle,
                  ),
                  child: Icon(item['icon'], color: itemColor, size: 24),
                ),
                const SizedBox(width: 16),
                
                // Content
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Expanded(
                            child: Text(
                              item['title'],
                              style: theme.textTheme.bodyLarge?.copyWith(
                                fontWeight: FontWeight.bold,
                                fontSize: 16,
                              ),
                            ),
                          ),
                          Text(
                            item['time'],
                            style: TextStyle(
                              fontSize: 12,
                              fontWeight: FontWeight.w500,
                              color: Colors.grey[500],
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 4),
                      Text(
                        item['body'],
                        style: theme.textTheme.bodyMedium?.copyWith(
                          height: 1.4,
                          color: isDark ? Colors.grey[300] : Colors.grey[700],
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}