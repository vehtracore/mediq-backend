import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

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
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;

    return Scaffold(
      backgroundColor: theme.scaffoldBackgroundColor, // ✅ Dynamic Background
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
          boxShadow: isDark
              ? [] // No shadow in dark mode for cleaner look
              : [
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
          backgroundColor: theme.cardTheme.color, // ✅ Dynamic Nav Bar
          selectedItemColor: const Color(0xFF4A90E2),
          unselectedItemColor: isDark ? Colors.grey[500] : Colors.grey[400],
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
    final theme = Theme.of(context);

    return Stack(
      children: [
        SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 24.0, vertical: 24.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // ✅ WIRED: Passes full user object to Header for Avatar + Name
              userAsync.when(
                data: (user) => HomeHeader(user: user),
                loading: () => const HomeHeader(user: null),
                error: (e, _) => const HomeHeader(user: null),
              ),
              const SizedBox(height: 32),

              const AppointmentCard(), // ✅ Real Data (via Provider in widget)

              // --- AI CARD ---
              const SizedBox(height: 24),
              _buildAICard(theme),

              const SizedBox(height: 24),
              Text(
                "Quick Actions",
                style: theme.textTheme.titleLarge?.copyWith(
                  fontWeight: FontWeight.bold,
                ),
              ),
              const SizedBox(height: 16),
              const QuickActionGrid(),
              const SizedBox(height: 180),
            ],
          ),
        ),
        NotificationListener<DraggableScrollableNotification>(
          onNotification: (n) {
            if (n.extent > 0.8 && !_showFab) {
              setState(() => _showFab = true);
            } else if (n.extent <= 0.8 && _showFab) {
              setState(() => _showFab = false);
            }
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

  Widget _buildAICard(ThemeData theme) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: () => context.pushNamed('aiChat'),
        borderRadius: BorderRadius.circular(16),
        child: Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            gradient: const LinearGradient(
              colors: [Color(0xFF6B8EFF), Color(0xFF4A90E2)],
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
            ),
            borderRadius: BorderRadius.circular(16),
            boxShadow: [
              BoxShadow(
                color: const Color(0xFF4A90E2).withOpacity(0.3),
                blurRadius: 10,
                offset: const Offset(0, 4),
              ),
            ],
          ),
          child: Row(
            children: [
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: Colors.white.withOpacity(0.2),
                  shape: BoxShape.circle,
                ),
                child: const Icon(Icons.auto_awesome,
                    color: Colors.white, size: 24),
              ),
              const SizedBox(width: 16),
              const Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      "AI Symptom Checker",
                      style: TextStyle(
                        color: Colors.white,
                        fontSize: 16,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    SizedBox(height: 4),
                    Text(
                      "Describe your symptoms & get instant advice.",
                      style: TextStyle(
                        color: Colors.white70,
                        fontSize: 12,
                      ),
                    ),
                  ],
                ),
              ),
              const Icon(Icons.arrow_forward_ios,
                  color: Colors.white70, size: 16),
            ],
          ),
        ),
      ),
    );
  }
}