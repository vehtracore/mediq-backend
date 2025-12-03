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
import '../../features/doctors/presentation/doctor_search_screen.dart';
import '../../features/doctors/presentation/doctor_detail_screen.dart';
import '../../features/doctors/data/doctor_model.dart';
import '../../features/appointments/presentation/book_appointment_screen.dart';
import '../../features/appointments/data/appointment_model.dart';
import '../../features/auth/data/auth_repository.dart';
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

final goRouterProvider = Provider<GoRouter>((ref) {
  return GoRouter(
    initialLocation: '/',
    routes: [
      GoRoute(path: '/', builder: (context, state) => const SplashScreen()),
      GoRoute(
        path: '/onboarding',
        builder: (context, state) => const OnboardingScreen(),
      ),
      GoRoute(
        path: '/safety_disclaimer',
        builder: (context, state) => const SafetyDisclaimerScreen(),
      ),
      GoRoute(path: '/auth', builder: (context, state) => const AuthScreen()),
      GoRoute(
        path: '/patient_home',
        builder: (context, state) => const PatientHomeScreen(),
      ),
      GoRoute(
        path: '/doctor_home',
        builder: (context, state) => const DoctorHomeScreen(),
      ),
      GoRoute(
        path: '/doctor_register',
        builder: (context, state) => const DoctorRegisterScreen(),
      ),
      GoRoute(
        path: '/doctor_pending',
        builder: (context, state) => const DoctorPendingScreen(),
      ),
      GoRoute(
        path: '/admin_dashboard',
        builder: (context, state) => const AdminDashboard(),
      ),
      GoRoute(
        path: '/find_doctor',
        builder: (context, state) => const DoctorSearchScreen(),
      ),
      GoRoute(
        path: '/notifications',
        builder: (context, state) => const NotificationsScreen(),
      ),
      GoRoute(
        path: '/settings',
        builder: (context, state) => const SettingsScreen(),
      ),
      GoRoute(
        path: '/medical_history',
        builder: (context, state) => const MedicalHistoryScreen(),
      ),
      GoRoute(
        path: '/doctor_availability',
        builder: (context, state) => const DoctorAvailabilityScreen(),
      ),
      GoRoute(
        path: '/emergency',
        builder: (context, state) => const EmergencyScreen(),
      ),
      GoRoute(
        path: '/subscription',
        builder: (context, state) => const SubscriptionScreen(),
      ),

      GoRoute(
        path: '/doctor_edit_profile',
        builder: (context, state) {
          final doctor = state.extra as Doctor;
          return DoctorEditProfileScreen(doctor: doctor);
        },
      ),

      // --- FIXED CHAT ROUTE (WEB SAFE) ---
      GoRoute(
        path: '/chat',
        builder: (context, state) {
          final extra = state.extra as Map<String, dynamic>?;
          final title = extra?['title'] as String? ?? "Health Assistant";
          final isAi = extra?['isAi'] as bool? ?? true;
          // NEW: Extract ID
          final apptId = extra?['appointmentId'] as int?;

          return ChatScreen(
            chatTitle: title,
            isAi: isAi,
            appointmentId: apptId,
          );
        },
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
        path: '/payment',
        builder: (context, state) {
          final data = state.extra as Map;
          return PaymentScreen(
            appointment: data['appointment'] as Appointment,
            amount: (data['amount'] as num).toDouble(),
          );
        },
      ),
    ],
  );
});
