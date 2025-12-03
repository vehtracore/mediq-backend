
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

// --- NEW: Real Stats Provider ---
final doctorStatsProvider = FutureProvider.autoDispose((ref) async {
  return await ref.watch(doctorRepositoryProvider).getDoctorStats();
});

class DoctorHomeScreen extends ConsumerStatefulWidget {
  const DoctorHomeScreen({super.key});
  @override ConsumerState<DoctorHomeScreen> createState() => _DoctorHomeScreenState();
}

class _DoctorHomeScreenState extends ConsumerState<DoctorHomeScreen> {
  int _selectedIndex = 0;
  static const List<Widget> _pages = [_DoctorDashboardTab(), DoctorRequestsScreen(), DoctorScheduleScreen(), DoctorProfileScreen()];
  @override Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF9FAFB),
      body: SafeArea(child: IndexedStack(index: _selectedIndex, children: _pages)),
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _selectedIndex, onTap: (i) => setState(() => _selectedIndex = i),
        type: BottomNavigationBarType.fixed, backgroundColor: Colors.white, selectedItemColor: const Color(0xFF4A90E2), unselectedItemColor: Colors.grey[400],
        items: const [BottomNavigationBarItem(icon: Icon(Icons.dashboard_outlined), label: 'Overview'), BottomNavigationBarItem(icon: Icon(Icons.notifications_none), label: 'Requests'), BottomNavigationBarItem(icon: Icon(Icons.calendar_today_outlined), label: 'Schedule'), BottomNavigationBarItem(icon: Icon(Icons.person_outline), label: 'Profile')],
      ),
    );
  }
}

class _DoctorDashboardTab extends ConsumerWidget {
  const _DoctorDashboardTab();
  @override Widget build(BuildContext context, WidgetRef ref) {
    final userAsync = ref.watch(userProvider);
    final requestsAsync = ref.watch(requestsControllerProvider);
    final scheduleAsync = ref.watch(doctorScheduleProvider);
    final statsAsync = ref.watch(doctorStatsProvider); // REAL STATS

    return SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        userAsync.when(data: (user) => Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text("Good Morning,", style: TextStyle(color: Colors.grey[600])), Text("Dr. ${user.lastName}", style: const TextStyle(fontSize: 24, fontWeight: FontWeight.bold))]), IconButton(icon: const CircleAvatar(child: Icon(Icons.notifications)), onPressed: () => context.push('/notifications'))]), loading: () => const SizedBox(), error: (e,s)=>const SizedBox()),
        const SizedBox(height: 32),
        Row(children: [
          Expanded(child: _buildStatCard("Pending", requestsAsync.value?.length.toString() ?? "0", Icons.assignment_ind, Colors.orange)),
          const SizedBox(width: 16),
          Expanded(child: _buildStatCard("Upcoming", scheduleAsync.value?.length.toString() ?? "0", Icons.calendar_today, Colors.blue)),
        ]),
        const SizedBox(height: 16),
        statsAsync.when(
          data: (stats) => Row(children: [
            Expanded(child: _buildStatCard("Earnings", "₦${stats['earnings']}", Icons.payments, Colors.green)),
            const SizedBox(width: 16),
            Expanded(child: _buildStatCard("Rating", "${stats['rating']}", Icons.star, Colors.purple)),
          ]),
          loading: () => const LinearProgressIndicator(),
          error: (e,s) => const Text("Stats Error"),
        ),
      ]),
    );
  }

  Widget _buildStatCard(String title, String value, IconData icon, Color color) {
    return Container(padding: const EdgeInsets.all(20), decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(20), boxShadow: [BoxShadow(color: Colors.grey.withOpacity(0.1), blurRadius: 10)]), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Icon(icon, color: color, size: 24), const SizedBox(height: 12), Text(value, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold)), Text(title, style: TextStyle(fontSize: 12, color: Colors.grey))]));
  }
}
