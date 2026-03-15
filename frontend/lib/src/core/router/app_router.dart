import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

// Feature Imports
import '../../features/splash/splash_screen.dart';
import '../../features/onboarding/onboarding_screens.dart';
import '../../features/auth/auth_screen.dart';
import '../../features/auth/presentation/doctor_register_screen.dart';
import '../../features/auth/presentation/doctor_pending_screen.dart';
import '../../features/patient_dashboard/patient_home_screen.dart';
import '../../features/doctor_dashboard/presentation/doctor_home_screen.dart';
import '../../features/chat/presentation/chat_screen.dart';
import '../../features/chat/presentation/ai_chat_screen.dart';
import '../../features/doctors/presentation/doctor_search_screen.dart';
import '../../features/doctors/presentation/doctor_detail_screen.dart';
import '../../features/doctors/data/doctor_model.dart';
import '../../features/appointments/presentation/book_appointment_screen.dart';
import '../../features/appointments/data/appointment_model.dart';

// --- IMPORTS ---
import '../../features/auth/data/auth_repository.dart' hide User;
import '../../features/auth/data/user_model.dart';
// ----------------

import '../../features/profile/presentation/edit_profile_screen.dart';
import '../../features/payments/presentation/payment_screen.dart';
import '../../features/notifications/presentation/notifications_screen.dart';
import '../../features/profile/presentation/settings_screen.dart';
import '../../features/profile/presentation/medical_history_screen.dart';
import '../../features/admin/presentation/admin_dashboard.dart';
import '../../features/doctor_dashboard/presentation/doctor_edit_profile_screen.dart';
import '../../features/doctor_dashboard/presentation/doctor_availability_screen.dart';
import '../../features/emergency/presentation/emergency_screen.dart';
import '../../features/subscription/presentation/subscription_screen.dart';
import 'package:mediq_app/src/features/chat/presentation/video_call_screen.dart';
import '../../features/profile/presentation/medical_history_screen.dart';
import '../../features/lab/presentation/lab_scanner_screen.dart';

// Global key so Dio interceptor can navigate imperatively
final rootNavigatorKey = GlobalKey<NavigatorState>();

final goRouterProvider = Provider<GoRouter>((ref) {
  return GoRouter(
    navigatorKey: rootNavigatorKey,
    initialLocation: '/',
    routes: [
      GoRoute(path: '/', builder: (context, state) => const SplashScreen()),
      GoRoute(
          path: '/onboarding',
          builder: (context, state) => const OnboardingScreen()),
      GoRoute(
          path: '/safety_disclaimer',
          builder: (context, state) => const SafetyDisclaimerScreen()),
      GoRoute(path: '/auth', builder: (context, state) => const AuthScreen()),
      GoRoute(
          path: '/patient_home',
          builder: (context, state) => const PatientHomeScreen()),
      GoRoute(
          path: '/doctor_home',
          builder: (context, state) => const DoctorHomeScreen()),
      GoRoute(
          path: '/doctor_register',
          builder: (context, state) => const DoctorRegisterScreen()),
      GoRoute(
          path: '/doctor_pending',
          builder: (context, state) => const DoctorPendingScreen()),
      GoRoute(
          path: '/admin_dashboard',
          builder: (context, state) => const AdminDashboard()),
      GoRoute(
          path: '/find_doctor',
          builder: (context, state) => const DoctorSearchScreen()),
      GoRoute(
          path: '/notifications',
          builder: (context, state) => const NotificationsScreen()),
      GoRoute(
          path: '/settings',
          builder: (context, state) => const SettingsScreen()),
      GoRoute(
          path: '/medical_history',
          builder: (context, state) => const MedicalHistoryScreen()),
      GoRoute(
          path: '/doctor_availability',
          builder: (context, state) => const DoctorAvailabilityScreen()),
      GoRoute(
          path: '/emergency',
          builder: (context, state) => const EmergencyScreen()),
      GoRoute(
          path: '/subscription',
          builder: (context, state) => const SubscriptionScreen()),

      GoRoute(
        path: '/doctor_edit_profile',
        builder: (context, state) {
          final doctor = state.extra as Doctor;
          return DoctorEditProfileScreen(doctor: doctor);
        },
      ),

      // --- FIX: SMART CHAT ROUTING ---
      GoRoute(
        path: '/chat',
        builder: (context, state) {
          final extra = state.extra as Map<String, dynamic>;

          // 1. Check if ID is missing or null. If so, it's the AI Chat.
          if (extra['appointmentId'] == null) {
            return const AiChatScreen();
          }

          // 2. Otherwise, open the standard Doctor Chat
          return ChatScreen(
            appointmentId: extra['appointmentId'], // This is now safe
            title: extra['title'] ?? 'Chat',
          );
        },
      ),
      // --------------------------------

      GoRoute(
        path: '/ai-chat',
        name: 'aiChat',
        builder: (context, state) => const AiChatScreen(),
      ),

      GoRoute(
        path: '/doctor_detail',
        builder: (context, state) {
          final doctor = state.extra as Doctor;
          return DoctorDetailScreen(doctor: doctor);
        },
      ),
      GoRoute(
        path: '/book_appointment',
        builder: (context, state) {
          final doctor = state.extra as Doctor;
          return BookAppointmentScreen(doctor: doctor);
        },
      ),

      GoRoute(
        path: '/edit_profile',
        builder: (context, state) {
          final user = state.extra as User;
          return EditProfileScreen(user: user);
        },
      ),

      GoRoute(
        path: '/video_call',
        builder: (context, state) {
          final appointmentId = state.extra as int;
          final isVoice = state.uri.queryParameters['type'] == 'voice';

          return VideoCallScreen(
            appointmentId: appointmentId,
            isVoiceCall: isVoice,
          );
        },
      ),

      GoRoute(
        path: '/payment',
        builder: (context, state) {
          final data = state.extra as Map;
          return PaymentScreen(
            appointment: data['appointment'] as Appointment,
            amount: (data['amount'] as num).toDouble(),
          );
        },
      ),
      GoRoute(
        path: '/lab_scanner',
        builder: (context, state) => const LabScannerScreen(),
      ),
    ],
  );
});
