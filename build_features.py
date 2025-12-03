import os

# This script generates the missing UI screens and fixes the Chat UI.

files = {
    # 1. FIX: Chat Screen (Added Spacing + Human Mode UI)
    "frontend/lib/src/features/chat/presentation/chat_screen.dart": """
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:mediq_app/src/features/chat/presentation/chat_controller.dart';

class ChatScreen extends ConsumerStatefulWidget {
  final String chatTitle;
  final bool isAi;

  const ChatScreen({
    super.key,
    this.chatTitle = "Health Assistant",
    this.isAi = true,
  });

  @override
  ConsumerState<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends ConsumerState<ChatScreen> {
  final TextEditingController _textController = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  late List<Map<String, dynamic>> _messages;

  @override
  void initState() {
    super.initState();
    if (widget.isAi) {
      _messages = [
        {"text": "Hello! I'm MedIQ. How can I help you today?", "isUser": false, "isLoading": false}
      ];
    } else {
      _messages = []; // Empty for human chat
    }
  }

  final List<String> _suggestions = [
    "Check my symptoms", "Speak to a doctor", "Find a pharmacy", "Emergency help"
  ];

  Future<void> _handleSend([String? manualText]) async {
    final text = manualText ?? _textController.text.trim();
    if (text.isEmpty) return;

    setState(() {
      _messages.add({"text": text, "isUser": true, "isLoading": false});
      if (widget.isAi) {
        _messages.add({"text": "Thinking...", "isUser": false, "isLoading": true});
      }
    });

    _textController.clear();
    _scrollToBottom();

    if (widget.isAi) {
      try {
        final response = await ref.read(chatControllerProvider.notifier).sendMessage(text);
        if (!mounted) return;
        setState(() {
          _messages.last['text'] = response;
          _messages.last['isLoading'] = false;
        });
      } catch (e) {
        if (!mounted) return;
        setState(() {
          _messages.last['text'] = "Connection Error. Please try again.";
          _messages.last['isLoading'] = false;
        });
      }
    }
    _scrollToBottom();
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 400),
          curve: Curves.easeOutQuad,
        );
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final bool isInitialAi = widget.isAi && _messages.length == 1;
    final Color appBarColor = widget.isAi ? const Color(0xFF4A90E2) : Colors.white;
    final Color iconColor = widget.isAi ? Colors.white : Colors.black87;
    final Color textColor = widget.isAi ? Colors.white : const Color(0xFF2D3436);

    return Scaffold(
      backgroundColor: const Color(0xFFF9FAFB),
      appBar: AppBar(
        backgroundColor: appBarColor,
        elevation: 0,
        centerTitle: false,
        leading: IconButton(
          icon: Icon(Icons.arrow_back_ios_new_rounded, color: iconColor),
          onPressed: () => Navigator.of(context).pop(),
        ),
        title: Row(
          children: [
            Container(
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: widget.isAi ? Colors.white.withOpacity(0.2) : const Color(0xFF4A90E2).withOpacity(0.1),
                shape: BoxShape.circle,
              ),
              child: Icon(
                widget.isAi ? Icons.smart_toy_rounded : Icons.person,
                size: 18,
                color: widget.isAi ? Colors.white : const Color(0xFF4A90E2),
              ),
            ),
            const SizedBox(width: 12),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(widget.chatTitle, style: TextStyle(color: textColor, fontWeight: FontWeight.bold, fontSize: 16)),
                if (!widget.isAi)
                  const Text("Online", style: TextStyle(color: Colors.green, fontSize: 12)),
              ],
            ),
          ],
        ),
        actions: [
          if (!widget.isAi) ...[
            IconButton(icon: const Icon(Icons.videocam_outlined), color: iconColor, onPressed: () {}),
            IconButton(icon: const Icon(Icons.call_outlined), color: iconColor, onPressed: () {}),
            const SizedBox(width: 8),
          ]
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: _messages.isEmpty
              ? Center(child: Text("Start consultation with ${widget.chatTitle}", style: TextStyle(color: Colors.grey[400])))
              : ListView.builder(
                  controller: _scrollController,
                  padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 20),
                  itemCount: _messages.length,
                  itemBuilder: (context, index) {
                    final msg = _messages[index];
                    return _buildMessageBubble(msg['text'], msg['isUser'], isLoading: msg['isLoading'] ?? false);
                  },
                ),
          ),
          if (isInitialAi)
            Container(
              height: 50, margin: const EdgeInsets.only(bottom: 10),
              child: ListView.separated(
                padding: const EdgeInsets.symmetric(horizontal: 20),
                scrollDirection: Axis.horizontal,
                itemCount: _suggestions.length,
                separatorBuilder: (_, __) => const SizedBox(width: 8),
                itemBuilder: (context, index) {
                  return ActionChip(
                    elevation: 0, backgroundColor: Colors.white,
                    side: BorderSide(color: const Color(0xFF4A90E2).withOpacity(0.2)),
                    label: Text(_suggestions[index], style: const TextStyle(color: Color(0xFF4A90E2), fontWeight: FontWeight.w600)),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
                    onPressed: () => _handleSend(_suggestions[index]),
                  );
                },
              ),
            ),
          SafeArea(
            child: Container(
              margin: const EdgeInsets.fromLTRB(16, 0, 16, 16),
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(32), boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 20, offset: const Offset(0, 10))]),
              child: Row(
                children: [
                  IconButton(icon: Icon(Icons.add_a_photo_rounded, color: Colors.grey[400]), onPressed: () {}),
                  Expanded(
                    child: TextField(
                      controller: _textController,
                      textCapitalization: TextCapitalization.sentences,
                      decoration: InputDecoration(
                        hintText: widget.isAi ? "Describe symptoms..." : "Type a message...",
                        hintStyle: TextStyle(color: Colors.grey[400]),
                        border: InputBorder.none,
                      ),
                      onSubmitted: (val) => _handleSend(),
                    ),
                  ),
                  const SizedBox(width: 12), // FIX: Added Spacing
                  GestureDetector(
                    onTap: () => _handleSend(),
                    child: Container(
                      padding: const EdgeInsets.all(10),
                      decoration: const BoxDecoration(shape: BoxShape.circle, color: Color(0xFF4A90E2)),
                      child: const Icon(Icons.arrow_upward_rounded, color: Colors.white, size: 20),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildMessageBubble(String text, bool isUser, {bool isLoading = false}) {
    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.only(bottom: 16),
        constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.8),
        decoration: BoxDecoration(
          color: isUser ? const Color(0xFF4A90E2) : Colors.white,
          borderRadius: BorderRadius.only(
            topLeft: const Radius.circular(24),
            topRight: const Radius.circular(24),
            bottomLeft: isUser ? const Radius.circular(24) : const Radius.circular(4),
            bottomRight: isUser ? const Radius.circular(4) : const Radius.circular(24),
          ),
          boxShadow: [if (!isUser) BoxShadow(color: Colors.grey.withOpacity(0.05), blurRadius: 10, offset: const Offset(0, 5))],
        ),
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
        child: isLoading 
          ? SizedBox(width: 40, height: 20, child: Center(child: SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.grey[300]))))
          : MarkdownBody(data: text, styleSheet: MarkdownStyleSheet(p: TextStyle(color: isUser ? Colors.white : const Color(0xFF2D3436), fontSize: 15, height: 1.5))),
      ),
    );
  }
}
""",

    # 2. NEW: Chat List Screen (The "Chat" Tab)
    "frontend/lib/src/features/chat/presentation/chat_list_screen.dart": """
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';
import '../../appointments/data/appointment_model.dart';
import '../../appointments/data/appointment_repository.dart';

final chatAppointmentsProvider = FutureProvider.autoDispose<List<Appointment>>((ref) async {
  final repo = ref.watch(appointmentRepositoryProvider);
  final allAppointments = await repo.getMyAppointments();
  return allAppointments.where((a) => a.status == 'confirmed').toList();
});

class ChatListScreen extends ConsumerWidget {
  const ChatListScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final appointmentsAsync = ref.watch(chatAppointmentsProvider);

    return Scaffold(
      backgroundColor: const Color(0xFFF9FAFB),
      appBar: AppBar(
        title: const Text("Messages", style: TextStyle(color: Colors.black, fontWeight: FontWeight.bold)),
        backgroundColor: Colors.white,
        elevation: 0,
        centerTitle: false,
        automaticallyImplyLeading: false,
      ),
      body: appointmentsAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (err, stack) => Center(child: Text("Error: $err")),
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
                child: Text("Doctor Consultations", style: TextStyle(fontWeight: FontWeight.bold, color: Colors.grey)),
              ),
              if (appointments.isEmpty)
                _buildEmptyState()
              else
                ...appointments.map((appt) => _DoctorChatTile(appointment: appt)),
            ],
          );
        },
      ),
    );
  }

  Widget _buildEmptyState() {
    return Container(
      padding: const EdgeInsets.all(24),
      alignment: Alignment.center,
      child: Column(children: [
        Icon(Icons.chat_bubble_outline, size: 48, color: Colors.grey[300]),
        const SizedBox(height: 12),
        Text("No upcoming consultations.", style: TextStyle(color: Colors.grey[500])),
      ]),
    );
  }
}

class _ChatTile extends StatelessWidget {
  final String name;
  final String subtitle;
  final String time;
  final bool isAi;
  final VoidCallback onTap;
  const _ChatTile({required this.name, required this.subtitle, required this.time, this.isAi = false, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(16), boxShadow: [BoxShadow(color: Colors.grey.withOpacity(0.05), blurRadius: 10, offset: const Offset(0, 4))]),
      child: ListTile(
        onTap: onTap,
        contentPadding: const EdgeInsets.all(12),
        leading: Container(width: 50, height: 50, decoration: BoxDecoration(color: const Color(0xFF4A90E2).withOpacity(0.1), shape: BoxShape.circle), child: const Icon(Icons.smart_toy_outlined, color: Color(0xFF4A90E2))),
        title: Text(name, style: const TextStyle(fontWeight: FontWeight.bold)),
        subtitle: Text(subtitle, style: const TextStyle(color: Color(0xFF4A90E2), fontSize: 12)),
        trailing: Text(time, style: TextStyle(color: Colors.grey[400], fontSize: 12)),
      ),
    );
  }
}

class _DoctorChatTile extends StatelessWidget {
  final Appointment appointment;
  const _DoctorChatTile({required this.appointment});

  @override
  Widget build(BuildContext context) {
    final now = DateTime.now();
    final unlockTime = appointment.startTime.subtract(const Duration(minutes: 10));
    final isUnlocked = now.isAfter(unlockTime);
    final timeStr = DateFormat('MMM dd, h:mm a').format(appointment.startTime);

    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(16), boxShadow: [BoxShadow(color: Colors.grey.withOpacity(0.05), blurRadius: 10, offset: const Offset(0, 4))]),
      child: ListTile(
        contentPadding: const EdgeInsets.all(12),
        onTap: () {
          if (isUnlocked) {
            context.push('/chat', extra: {'title': appointment.doctorName, 'isAi': false});
          } else {
            ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Chat opens 10 minutes before appointment."), backgroundColor: Colors.orange));
          }
        },
        leading: CircleAvatar(radius: 25, backgroundColor: Colors.grey[200], child: Text(appointment.doctorName.isNotEmpty ? appointment.doctorName[0] : "D")),
        title: Text(appointment.doctorName, style: const TextStyle(fontWeight: FontWeight.bold)),
        subtitle: Text("Consultation at $timeStr", style: TextStyle(color: Colors.grey[600], fontSize: 12)),
        trailing: Icon(isUnlocked ? Icons.videocam : Icons.lock_outline, color: isUnlocked ? Colors.green : Colors.grey),
      ),
    );
  }
}
""",

    # 3. NEW: Notifications Screen
    "frontend/lib/src/features/notifications/presentation/notifications_screen.dart": """
import 'package:flutter/material.dart';

class NotificationsScreen extends StatelessWidget {
  const NotificationsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final notifications = [
      {"title": "Appointment Confirmed", "body": "Your booking with Dr. Gregory House is confirmed.", "time": "10m ago", "color": Colors.green, "icon": Icons.event_available},
      {"title": "Welcome to MedIQ", "body": "We are glad to have you! Start by setting up your profile.", "time": "1d ago", "color": const Color(0xFF4A90E2), "icon": Icons.health_and_safety_outlined},
    ];

    return Scaffold(
      backgroundColor: const Color(0xFFF9FAFB),
      appBar: AppBar(title: const Text("Notifications", style: TextStyle(color: Colors.black, fontWeight: FontWeight.bold)), backgroundColor: Colors.white, elevation: 0, iconTheme: const IconThemeData(color: Colors.black)),
      body: ListView.separated(
        padding: const EdgeInsets.all(16),
        itemCount: notifications.length,
        separatorBuilder: (_, __) => const SizedBox(height: 12),
        itemBuilder: (context, index) {
          final item = notifications[index];
          return Container(
            decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(12), boxShadow: [BoxShadow(color: Colors.grey.withOpacity(0.05), blurRadius: 8, offset: const Offset(0, 2))]),
            child: ListTile(
              leading: CircleAvatar(backgroundColor: (item['color'] as Color).withOpacity(0.1), child: Icon(item['icon'] as IconData, color: item['color'] as Color)),
              title: Text(item['title'] as String, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15)),
              subtitle: Text(item['body'] as String, style: TextStyle(fontSize: 13, color: Colors.grey[600])),
              trailing: Text(item['time'] as String, style: TextStyle(fontSize: 12, color: Colors.grey[400])),
            ),
          );
        },
      ),
    );
  }
}
""",

    # 4. NEW: Medical History Screen
    "frontend/lib/src/features/profile/presentation/medical_history_screen.dart": """
import 'package:flutter/material.dart';
class MedicalHistoryScreen extends StatelessWidget {
  const MedicalHistoryScreen({super.key});
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF9FAFB),
      appBar: AppBar(title: const Text("Medical History", style: TextStyle(color: Colors.black)), backgroundColor: Colors.white, elevation: 0, iconTheme: const IconThemeData(color: Colors.black)),
      body: Center(child: Text("No history yet", style: TextStyle(color: Colors.grey[500]))),
    );
  }
}
""",

    # 5. NEW: Settings Screen
    "frontend/lib/src/features/profile/presentation/settings_screen.dart": """
import 'package:flutter/material.dart';
class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF9FAFB),
      appBar: AppBar(title: const Text("Settings", style: TextStyle(color: Colors.black)), backgroundColor: Colors.white, elevation: 0, iconTheme: const IconThemeData(color: Colors.black)),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        SwitchListTile(value: true, onChanged: (v){}, title: const Text("Push Notifications")),
        const Divider(),
        ListTile(title: const Text("Terms of Service"), trailing: const Icon(Icons.chevron_right)),
        ListTile(title: const Text("Privacy Policy"), trailing: const Icon(Icons.chevron_right)),
      ]),
    );
  }
}
""",

    # 6. FIX: Doctor Schedule (Wire "Start Consultation")
    "frontend/lib/src/features/doctor_dashboard/presentation/doctor_schedule_screen.dart": """
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:go_router/go_router.dart';
import '../../appointments/data/appointment_model.dart';
import '../../appointments/data/appointment_repository.dart';

final doctorScheduleProvider = FutureProvider.autoDispose<List<Appointment>>((ref) async {
  final repo = ref.watch(appointmentRepositoryProvider);
  return await repo.getDoctorConfirmedAppointments();
});

class DoctorScheduleScreen extends ConsumerWidget {
  const DoctorScheduleScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final scheduleAsync = ref.watch(doctorScheduleProvider);

    return Scaffold(
      backgroundColor: Colors.white,
      body: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(padding: const EdgeInsets.fromLTRB(24, 24, 24, 16), child: Text("My Schedule", style: Theme.of(context).textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.bold, color: const Color(0xFF2D3436)))),
            Expanded(
              child: scheduleAsync.when(
                loading: () => const Center(child: CircularProgressIndicator()),
                error: (err, stack) => Center(child: Text("Error: $err")),
                data: (appointments) {
                  if (appointments.isEmpty) return const Center(child: Text("No upcoming appointments"));
                  return ListView.separated(
                    padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 8),
                    itemCount: appointments.length,
                    separatorBuilder: (_, __) => const SizedBox(height: 16),
                    itemBuilder: (context, index) => _AppointmentCard(appointment: appointments[index]),
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

class _AppointmentCard extends StatelessWidget {
  final Appointment appointment;
  const _AppointmentCard({required this.appointment});

  @override
  Widget build(BuildContext context) {
    final timeStr = DateFormat('jm').format(appointment.startTime);
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(16), boxShadow: [BoxShadow(color: Colors.grey.withOpacity(0.08), blurRadius: 10)]),
      child: Column(children: [
        Row(children: [
          Text(timeStr, style: const TextStyle(fontWeight: FontWeight.bold, color: Color(0xFF4A90E2))),
          const SizedBox(width: 16),
          Text(appointment.doctorName.isNotEmpty ? appointment.doctorName : "Patient", style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 18)),
        ]),
        const SizedBox(height: 16),
        SizedBox(
          width: double.infinity, height: 45,
          child: ElevatedButton.icon(
            onPressed: () => context.push('/chat', extra: {'title': appointment.doctorName, 'isAi': false}),
            icon: const Icon(Icons.videocam_outlined), label: const Text("Start Consultation"),
            style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF4A90E2), foregroundColor: Colors.white, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12))),
          ),
        ),
      ]),
    );
  }
}
""",

    # 7. FIX: Patient Dashboard (Uses ChatListScreen)
    "frontend/lib/src/features/patient_dashboard/patient_home_screen.dart": """
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
  final DraggableScrollableController _sheetController = DraggableScrollableController();
  bool _showFab = false;
  @override void dispose() { _sheetController.dispose(); super.dispose(); }
  void _onItemTapped(int index) { setState(() { _selectedIndex = index; }); }

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
        decoration: BoxDecoration(boxShadow: [BoxShadow(color: Colors.grey.withOpacity(0.1), blurRadius: 20, offset: const Offset(0, -5))]),
        child: BottomNavigationBar(
          currentIndex: _selectedIndex, onTap: _onItemTapped, type: BottomNavigationBarType.fixed, backgroundColor: Colors.white,
          selectedItemColor: const Color(0xFF4A90E2), unselectedItemColor: Colors.grey[400], showUnselectedLabels: true,
          items: const [
            BottomNavigationBarItem(icon: Icon(Icons.home_filled), label: "Home"),
            BottomNavigationBarItem(icon: Icon(Icons.calendar_today), label: "Schedule"),
            BottomNavigationBarItem(icon: Icon(Icons.chat_bubble_outline), label: "Chat"),
            BottomNavigationBarItem(icon: Icon(Icons.person_outline), label: "Profile"),
          ],
        ),
      ),
    );
  }

  Widget _buildHomeTab() {
    final userAsync = ref.watch(userProvider);
    return Stack(children: [
      SingleChildScrollView(
        padding: const EdgeInsets.symmetric(horizontal: 24.0, vertical: 24.0),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          userAsync.when(data: (user) => HomeHeader(userName: user.firstName), loading: () => const HomeHeader(userName: "..."), error: (e, _) => const HomeHeader(userName: "Guest")),
          const SizedBox(height: 32), const AppointmentCard(), const SizedBox(height: 32),
          Text("Quick Actions", style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.bold)),
          const SizedBox(height: 16), const QuickActionGrid(), const SizedBox(height: 180),
        ]),
      ),
      NotificationListener<DraggableScrollableNotification>(
        onNotification: (n) { if (n.extent > 0.8 && !_showFab) setState(() => _showFab = true); else if (n.extent <= 0.8 && _showFab) setState(() => _showFab = false); return true; },
        child: HealthTipsSheet(controller: _sheetController),
      ),
      AnimatedPositioned(
        duration: const Duration(milliseconds: 300), bottom: _showFab ? 20 : -100, right: 20,
        child: FloatingActionButton(mini: true, backgroundColor: const Color(0xFF4A90E2), child: const Icon(Icons.keyboard_arrow_down, color: Colors.white), onPressed: () { _sheetController.animateTo(0.15, duration: const Duration(milliseconds: 400), curve: Curves.easeOutBack); }),
      ),
    ]);
  }
}
"""
}

for path, content in files.items():
    full_path = path.replace("/", os.sep)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"✅ Fixed: {path}")