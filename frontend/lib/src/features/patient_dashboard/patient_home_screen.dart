import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/features/auth/presentation/user_controller.dart';
import 'package:mediq_app/src/features/patient_dashboard/presentation/widgets/home_widgets.dart';
import 'package:mediq_app/src/features/patient_dashboard/presentation/widgets/health_tips_sheet.dart';
import 'package:mediq_app/src/features/appointments/presentation/schedule_screen.dart';
import 'package:mediq_app/src/features/profile/presentation/profile_screen.dart';
import 'package:mediq_app/src/features/chat/presentation/chat_list_screen.dart';

class PatientHomeScreen extends ConsumerStatefulWidget {
  const PatientHomeScreen({super.key});
  @override
  ConsumerState<PatientHomeScreen> createState() => _PatientHomeScreenState();
}

class _PatientHomeScreenState extends ConsumerState<PatientHomeScreen> {
  int _selectedIndex = 0;
  final DraggableScrollableController _sheetController =
      DraggableScrollableController();
  bool _showFab = false;

  @override
  void dispose() {
    _sheetController.dispose();
    super.dispose();
  }

  void _onItemTapped(int index) {
    setState(() {
      _selectedIndex = index;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF9FAFB),
      body: SafeArea(
        child: IndexedStack(
          index: _selectedIndex,
          children: [
            _buildHomeTab(),
            const ScheduleScreen(),
            const ChatListScreen(),
            const ProfileScreen(),
          ],
        ),
      ),
      bottomNavigationBar: Container(
        decoration: BoxDecoration(
          boxShadow: [
            BoxShadow(
              color: Colors.grey.withOpacity(0.1),
              blurRadius: 20,
              offset: const Offset(0, -5),
            ),
          ],
        ),
        child: BottomNavigationBar(
          currentIndex: _selectedIndex,
          onTap: _onItemTapped,
          type: BottomNavigationBarType.fixed,
          backgroundColor: Colors.white,
          selectedItemColor: const Color(0xFF4A90E2),
          unselectedItemColor: Colors.grey[400],
          showUnselectedLabels: true,
          items: const [
            BottomNavigationBarItem(
              icon: Icon(Icons.home_filled),
              label: "Home",
            ),
            BottomNavigationBarItem(
              icon: Icon(Icons.calendar_today),
              label: "Schedule",
            ),
            BottomNavigationBarItem(
              icon: Icon(Icons.chat_bubble_outline),
              label: "Chat",
            ),
            BottomNavigationBarItem(
              icon: Icon(Icons.person_outline),
              label: "Profile",
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildHomeTab() {
    final userAsync = ref.watch(userProvider);
    return Stack(
      children: [
        SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 24.0, vertical: 24.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              userAsync.when(
                // REMOVED 'const' below
                data: (user) => HomeHeader(userName: user.firstName),
                loading: () => const HomeHeader(userName: "..."),
                error: (e, _) => const HomeHeader(userName: "Guest"),
              ),
              const SizedBox(height: 32),
              const AppointmentCard(),
              const SizedBox(height: 32),
              Text(
                "Quick Actions",
                style: Theme.of(
                  context,
                ).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 16),
              // REMOVED 'const' below
              const QuickActionGrid(),
              const SizedBox(height: 180),
            ],
          ),
        ),
        NotificationListener<DraggableScrollableNotification>(
          onNotification: (n) {
            if (n.extent > 0.8 && !_showFab)
              setState(() => _showFab = true);
            else if (n.extent <= 0.8 && _showFab)
              setState(() => _showFab = false);
            return true;
          },
          child: HealthTipsSheet(controller: _sheetController),
        ),
        AnimatedPositioned(
          duration: const Duration(milliseconds: 300),
          bottom: _showFab ? 20 : -100,
          right: 20,
          child: FloatingActionButton(
            mini: true,
            backgroundColor: const Color(0xFF4A90E2),
            child: const Icon(Icons.keyboard_arrow_down, color: Colors.white),
            onPressed: () {
              _sheetController.animateTo(
                0.15,
                duration: const Duration(milliseconds: 400),
                curve: Curves.easeOutBack,
              );
            },
          ),
        ),
      ],
    );
  }
}
