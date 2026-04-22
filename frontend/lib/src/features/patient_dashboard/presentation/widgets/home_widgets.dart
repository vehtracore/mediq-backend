import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';
import 'package:mediq_app/src/features/appointments/data/appointment_repository.dart';
import 'package:mediq_app/src/features/auth/presentation/user_controller.dart';
import 'package:mediq_app/src/features/appointments/data/appointment_model.dart';
import 'package:mediq_app/src/features/auth/data/user_model.dart'; // ✅ Added for User type

// ✅ REAL DATA PROVIDER: Fetches next confirmed appointment
final nextAppointmentProvider =
    FutureProvider.autoDispose<Appointment?>((ref) async {
  final appointments =
      await ref.watch(appointmentRepositoryProvider).getMyAppointments();
  final upcoming = appointments
      .where(
          (a) => a.status == 'confirmed' && a.startTime.isAfter(DateTime.now()))
      .toList();
  if (upcoming.isEmpty) return null;
  upcoming.sort((a, b) => a.startTime.compareTo(b.startTime));
  return upcoming.first;
});

class HomeHeader extends StatelessWidget {
  final User? user; // ✅ Accepts full User object for Avatar + Name
  const HomeHeader({super.key, this.user});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;
    
    // Data Extraction
    final userName = user?.firstName ?? "Guest";
    final imageUrl = user?.imageUrl;

    return Container(
      decoration: BoxDecoration(
        color: theme.scaffoldBackgroundColor,
      ),
      padding: const EdgeInsets.symmetric(vertical: 16),
      child: Row(
        children: [
          // ✅ 1. PROFILE PICTURE
          CircleAvatar(
            radius: 24,
            backgroundColor: theme.cardTheme.color,
            backgroundImage: (imageUrl != null && imageUrl.isNotEmpty)
                ? NetworkImage(imageUrl)
                : null,
            child: (imageUrl == null || imageUrl.isEmpty)
                ? Icon(Icons.person, color: Colors.grey[400])
                : null,
          ),
          const SizedBox(width: 16),
          
          // ✅ 2. USER WELCOME TEXT
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text("Welcome Back,",
                    style: theme.textTheme.bodyMedium?.copyWith(
                        fontSize: 14, fontWeight: FontWeight.w500)),
                Text(userName,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.headlineMedium?.copyWith(
                        fontSize: 24,
                        fontWeight: FontWeight.bold,
                        letterSpacing: -0.5)),
              ],
            ),
          ),

          // ✅ 3. NOTIFICATION ICON
          GestureDetector(
              onTap: () => context.push('/notifications'),
              child: Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                      color: theme.cardTheme.color,
                      borderRadius: BorderRadius.circular(16),
                      border: Border.all(
                          color: isDark
                              ? Colors.transparent
                              : Colors.grey.withOpacity(0.1)),
                      boxShadow: isDark
                          ? []
                          : [
                              BoxShadow(
                                  color: const Color(0xFF4A90E2).withOpacity(0.1),
                                  blurRadius: 15,
                                  offset: const Offset(0, 5))
                            ]),
                  child: const Icon(Icons.notifications_none_rounded,
                      color: Color(0xFF4A90E2), size: 26))),
        ],
      ),
    );
  }
}

class AppointmentCard extends ConsumerWidget {
  const AppointmentCard({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final nextApptAsync = ref.watch(nextAppointmentProvider);

    return nextApptAsync.when(
      loading: () => const SizedBox(
          height: 160, child: Center(child: CircularProgressIndicator())),
      error: (e, _) => const SizedBox(),
      data: (appointment) {
        // 1. EMPTY STATE (No confirmed appointments)
        if (appointment == null) {
          return Container(
            width: double.infinity,
            padding: const EdgeInsets.all(24),
            decoration: BoxDecoration(
              color: Theme.of(context).cardTheme.color,
              borderRadius: BorderRadius.circular(32),
              border: Border.all(color: Colors.grey.withOpacity(0.1)),
            ),
            child: Row(
              children: [
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: const Color(0xFF4A90E2).withOpacity(0.1),
                    shape: BoxShape.circle,
                  ),
                  child: const Icon(Icons.calendar_today,
                      color: Color(0xFF4A90E2)),
                ),
                const SizedBox(width: 16),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        "No upcoming visits",
                        style: Theme.of(context)
                            .textTheme
                            .bodyLarge
                            ?.copyWith(fontWeight: FontWeight.bold),
                      ),
                      const SizedBox(height: 4),
                      Text("Book a doctor to get started.",
                          style:
                              TextStyle(fontSize: 12, color: Colors.grey[600])),
                    ],
                  ),
                ),
                TextButton(
                  onPressed: () => context.push('/find_doctor'),
                  child: const Text("Book Now",
                      style: TextStyle(fontWeight: FontWeight.bold)),
                ),
              ],
            ),
          );
        }

        // 2. ACTIVE STATE (Show Appointment)
        final dateStr =
            DateFormat('MMM dd, yyyy').format(appointment.startTime);
        final timeStr = DateFormat('jm').format(appointment.startTime);

        return GestureDetector(
          onTap: () => context.go('/schedule'),
          child: Container(
            width: double.infinity,
            padding: const EdgeInsets.all(24),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(32),
              gradient: const LinearGradient(
                colors: [Color(0xFF4A90E2), Color(0xFF00CEC9)],
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
              ),
              boxShadow: [
                BoxShadow(
                  color: const Color(0xFF4A90E2).withOpacity(0.4),
                  blurRadius: 20,
                  offset: const Offset(0, 10),
                ),
              ],
            ),
            child: Column(
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 12, vertical: 6),
                      decoration: BoxDecoration(
                        color: Colors.white.withOpacity(0.2),
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Row(
                        children: [
                          const Icon(Icons.calendar_today_rounded,
                              color: Colors.white, size: 14),
                          const SizedBox(width: 6),
                          Text(
                            "$dateStr • $timeStr",
                            style: const TextStyle(
                                color: Colors.white,
                                fontWeight: FontWeight.bold,
                                fontSize: 12),
                          ),
                        ],
                      ),
                    ),
                    const Icon(Icons.videocam, color: Colors.white),
                  ],
                ),
                const SizedBox(height: 20),
                Row(
                  children: [
                    Container(
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        border: Border.all(
                            color: Colors.white.withOpacity(0.5), width: 2),
                      ),
                      child: const CircleAvatar(
                        radius: 26,
                        backgroundColor: Colors.white24,
                        child:
                            Icon(Icons.medical_services, color: Colors.white, size: 28),
                      ),
                    ),
                    const SizedBox(width: 16),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            appointment.doctorName,
                            style: const TextStyle(
                                color: Colors.white,
                                fontSize: 18,
                                fontWeight: FontWeight.bold),
                          ),
                          const SizedBox(height: 4),
                          const Text(
                            "Tap to view details",
                            style:
                                TextStyle(color: Colors.white70, fontSize: 13),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}

class QuickActionGrid extends ConsumerWidget {
  const QuickActionGrid({super.key});

  void _showBookingOptions(BuildContext context, WidgetRef ref) {
    // ✅ Safe Read: Use ref.read in callbacks (prevents rebuilds)
    final user = ref.read(userProvider).value; 
    
    String priceText = "Loading...";
    double priceVal = 4000.0;

    if (user != null) {
      if (user.subscriptionTier == 'premium') {
        priceText = "NGN 2,500 (Premium)";
        priceVal = 2500.0;
      } else {
        priceText = "NGN 4,000 (Standard)";
        priceVal = 4000.0;
      }
    }

    final theme = Theme.of(context);

    showModalBottomSheet(
        context: context,
        backgroundColor: Colors.transparent,
        builder: (ctx) => Container(
            padding: const EdgeInsets.all(24),
            decoration: BoxDecoration(
                color: theme.cardTheme.color, // ✅ Dynamic Sheet
                borderRadius:
                    const BorderRadius.vertical(top: Radius.circular(24))),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              ListTile(
                  title: Text("See a GP Now",
                      style: theme.textTheme.titleMedium
                          ?.copyWith(fontWeight: FontWeight.bold)),
                  subtitle: Text(priceText,
                      style: theme.textTheme.bodyMedium),
                  leading: const Icon(Icons.flash_on, color: Colors.orange),
                  onTap: () async {
                    Navigator.pop(ctx);
                    try {
                      final appt = await ref
                          .read(appointmentRepositoryProvider)
                          .bookGeneralConsultation("I need a doctor now.");
                      if (context.mounted)
                        context.push('/payment', extra: {
                          'transactionType': 'gp_consult',
                          'baseAmount': priceVal,
                          'title': 'General Consultation',
                        });
                    } catch (e) {
                      if (context.mounted)
                        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                            content: Text("Error: $e"),
                            backgroundColor: Colors.red));
                    }
                  }),
              const Divider(),
              ListTile(
                  title: Text("Book a Specialist",
                      style: theme.textTheme.bodyLarge),
                  leading: const Icon(Icons.calendar_month,
                      color: Color(0xFF4A90E2)),
                  onTap: () {
                    Navigator.pop(ctx);
                    context.push('/find_doctor');
                  })
            ])));
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;

    final actions = [
      {
        'icon': Icons.person_search_rounded,
        'label': 'Find Doctor',
        'color': 0xFF00CEC9
      },
      {'icon': Icons.phone_in_talk, 'label': 'Emergency', 'color': 0xFFFDCB6E}
    ];

    return GridView.builder(
        shrinkWrap: true,
        physics: const NeverScrollableScrollPhysics(),
        gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: 2,
            childAspectRatio: 1.5,
            crossAxisSpacing: 16,
            mainAxisSpacing: 16),
        itemCount: actions.length,
        itemBuilder: (context, index) {
          final item = actions[index];
          final color = Color(item['color'] as int);
          return InkWell(
              onTap: () {
                if (item['label'] == 'Find Doctor') {
                  _showBookingOptions(context, ref);
                } else if (item['label'] == 'Emergency') {
                  context.push('/emergency');
                }
              },
              borderRadius: BorderRadius.circular(24),
              child: Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                      color: theme.cardTheme.color,
                      borderRadius: BorderRadius.circular(24),
                      boxShadow: isDark
                          ? []
                          : [
                              BoxShadow(
                                  color: Colors.grey.withOpacity(0.05),
                                  blurRadius: 20,
                                  offset: const Offset(0, 5))
                            ]),
                  child: FittedBox(
                    fit: BoxFit.scaleDown,
                    child: Column(
                        mainAxisSize: MainAxisSize.min,
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Container(
                              padding: const EdgeInsets.all(12),
                              decoration: BoxDecoration(
                                  color: color.withOpacity(0.1),
                                  shape: BoxShape.circle),
                              child: Icon(item['icon'] as IconData,
                                  color: color, size: 28)),
                          const SizedBox(height: 12),
                          Text(item['label'] as String,
                              textAlign: TextAlign.center,
                              style: theme.textTheme.bodyMedium?.copyWith(
                                  fontWeight: FontWeight.bold,
                                  fontSize: 14))
                        ]),
                  )));
        });
  }
}