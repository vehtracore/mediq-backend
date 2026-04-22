import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:go_router/go_router.dart';
import 'package:mediq_app/src/features/auth/presentation/user_controller.dart';
import 'package:mediq_app/src/features/doctor_dashboard/presentation/doctor_requests_screen.dart';
import 'package:mediq_app/src/features/doctor_dashboard/presentation/doctor_profile_screen.dart';
import 'package:mediq_app/src/features/doctor_dashboard/presentation/doctor_schedule_screen.dart';
import 'package:mediq_app/src/features/doctor_dashboard/presentation/requests_controller.dart';
import 'package:mediq_app/src/features/doctors/data/doctor_repository.dart';

final doctorStatsProvider = FutureProvider.autoDispose((ref) async {
  return await ref.watch(doctorRepositoryProvider).getDoctorStats();
});

class DoctorHomeScreen extends ConsumerStatefulWidget {
  const DoctorHomeScreen({super.key});
  @override
  ConsumerState<DoctorHomeScreen> createState() => _DoctorHomeScreenState();
}

class _DoctorHomeScreenState extends ConsumerState<DoctorHomeScreen> {
  int _selectedIndex = 0;
  static const List<Widget> _pages = [
    _DoctorDashboardTab(),
    DoctorRequestsScreen(),
    DoctorScheduleScreen(),
    DoctorProfileScreen()
  ];
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Scaffold(
      backgroundColor: theme.scaffoldBackgroundColor, // ✅ Dynamic Background
      body: SafeArea(
          child: IndexedStack(index: _selectedIndex, children: _pages)),
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _selectedIndex,
        onTap: (i) => setState(() => _selectedIndex = i),
        type: BottomNavigationBarType.fixed,
        backgroundColor: theme.cardTheme.color, // ✅ Dynamic Nav Bar
        selectedItemColor: const Color(0xFF4A90E2),
        unselectedItemColor:
            theme.iconTheme.color?.withOpacity(0.5), // ✅ Dynamic Icon Color
        items: const [
          BottomNavigationBarItem(
              icon: Icon(Icons.dashboard_outlined), label: 'Overview'),
          BottomNavigationBarItem(
              icon: Icon(Icons.notifications_none), label: 'Requests'),
          BottomNavigationBarItem(
              icon: Icon(Icons.calendar_today_outlined), label: 'Schedule'),
          BottomNavigationBarItem(
              icon: Icon(Icons.person_outline), label: 'Profile')
        ],
      ),
    );
  }
}

class _DoctorDashboardTab extends ConsumerWidget {
  const _DoctorDashboardTab();
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final userAsync = ref.watch(userProvider);
    final requestsAsync = ref.watch(requestsControllerProvider);
    final scheduleAsync = ref.watch(doctorScheduleProvider);
    final statsAsync = ref.watch(doctorStatsProvider);
    final theme = Theme.of(context);

    return SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        userAsync.when(
            data: (user) => Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Expanded(
                        child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text("Good Morning,",
                                  style: theme
                                      .textTheme.bodyMedium), // ✅ Dynamic Text
                              Text("Dr. ${user?.lastName ?? ''}",
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: theme.textTheme.headlineSmall?.copyWith(
                                      fontWeight:
                                          FontWeight.bold)) // ✅ Dynamic Text
                            ]),
                      ),
                      IconButton(
                          icon: CircleAvatar(
                              backgroundColor:
                                  theme.brightness == Brightness.dark
                                      ? Colors.grey[800]
                                      : Colors.grey[200],
                              child: Icon(Icons.notifications,
                                  color: theme.iconTheme.color)),
                          onPressed: () => context.push('/notifications'))
                    ]),
            loading: () => const SizedBox(),
            error: (e, s) => const SizedBox()),
        const SizedBox(height: 32),
        Row(children: [
          Expanded(
              child: _buildStatCard(
                  context,
                  "Pending",
                  requestsAsync.value?.length.toString() ?? "0",
                  Icons.assignment_ind,
                  Colors.orange)),
          const SizedBox(width: 16),
          Expanded(
              child: _buildStatCard(
                  context,
                  "Upcoming",
                  scheduleAsync.value?.length.toString() ?? "0",
                  Icons.calendar_today,
                  Colors.blue)),
        ]),
        const SizedBox(height: 16),
        statsAsync.when(
          data: (stats) => Row(children: [
            Expanded(
                child: _buildStatCard(context, "Earnings",
                    "₦${stats['earnings']}", Icons.payments, Colors.green)),
            const SizedBox(width: 16),
            Expanded(
                child: _buildStatCard(context, "Rating", "${stats['rating']}",
                    Icons.star, Colors.purple)),
          ]),
          loading: () => const LinearProgressIndicator(),
          error: (e, s) => const Text("Stats Error"),
        ),
      ]),
    );
  }

  Widget _buildStatCard(BuildContext context, String title, String value,
      IconData icon, Color color) {
    final theme = Theme.of(context);

    return Container(
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(
            color: theme.cardTheme.color, // ✅ Dynamic Card Background
            borderRadius: BorderRadius.circular(20),
            boxShadow: theme.brightness == Brightness.dark
                ? [] // No shadow in dark mode
                : [
                    BoxShadow(
                        color: Colors.grey.withOpacity(0.1), blurRadius: 10)
                  ]),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(icon, color: color, size: 24),
          const SizedBox(height: 12),
          Text(value,
              style: theme.textTheme.titleLarge
                  ?.copyWith(fontWeight: FontWeight.bold)), // ✅ Dynamic Text
          Text(title, style: theme.textTheme.bodySmall) // ✅ Dynamic Text
        ]));
  }
}
