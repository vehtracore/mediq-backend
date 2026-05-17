import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart' hide User;

// Feature Imports
import '../../features/splash/splash_screen.dart';
import '../../features/onboarding/onboarding_screens.dart';
import '../../features/auth/auth_screen.dart';
import '../../features/auth/presentation/doctor_register_screen.dart';
import '../../features/auth/presentation/doctor_rejected_screen.dart';
import '../../features/patient_dashboard/patient_home_screen.dart';
import '../../features/doctor_dashboard/presentation/doctor_home_screen.dart';
import '../../features/chat/presentation/chat_screen.dart';
import '../../features/chat/presentation/ai_chat_screen.dart';
import '../../features/doctors/presentation/doctor_search_screen.dart';
import '../../features/doctors/presentation/doctor_detail_screen.dart';
import '../../features/doctors/data/doctor_model.dart';
import '../../features/appointments/presentation/book_appointment_screen.dart';

// --- IMPORTS ---
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
import '../../features/lab/presentation/lab_scanner_screen.dart';
import '../../features/profile/presentation/payout_settings_screen.dart';
import '../../features/subscription/presentation/family_dashboard_screen.dart';
import '../../features/auth/presentation/update_password_screen.dart';

// Global key so Dio interceptor can navigate imperatively
final rootNavigatorKey = GlobalKey<NavigatorState>();

// ---------------------------------------------------------------------------
// Supabase Auth State Provider
// ---------------------------------------------------------------------------
// Listens to the Supabase auth stream so the router can reactively redirect
// on every session change (sign-in, sign-out, token refresh).
// Using AuthState (not Session?) so we can distinguish between
// "not yet loaded" (waiting) and "loaded but null" (logged out).
// ---------------------------------------------------------------------------
final supabaseAuthProvider = StreamProvider<AuthState>((ref) {
  return Supabase.instance.client.auth.onAuthStateChange;
});

// Tracks whether the current session is a password-recovery flow.
// GoRouter reads this via redirect to send the user to /update-password
// instead of a normal dashboard.
final _isPasswordRecoveryProvider = StateProvider<bool>((ref) => false);

// Public alias consumed by the router provider (keeps ref.watch tidy).
final passwordRecoveryProvider = _isPasswordRecoveryProvider;

final goRouterProvider = Provider<GoRouter>((ref) {
  // Watch the auth stream so GoRouter rebuilds on every session change.
  final authState = ref.watch(supabaseAuthProvider);

  // Detect PASSWORD_RECOVERY events from the Supabase stream and set the flag.
  ref.listen<AsyncValue<AuthState>>(supabaseAuthProvider, (_, next) {
    next.whenData((state) {
      if (state.event == AuthChangeEvent.passwordRecovery) {
        ref.read(_isPasswordRecoveryProvider.notifier).state = true;
      } else if (state.event == AuthChangeEvent.signedIn) {
        // Only clear recovery flag on a genuine sign-in (not the temp recovery session)
        ref.read(_isPasswordRecoveryProvider.notifier).state = false;
      }
    });
  });

  final isPasswordRecovery = ref.watch(_isPasswordRecoveryProvider);

  return GoRouter(
    navigatorKey: rootNavigatorKey,
    initialLocation: '/',
    // -------------------------------------------------------------------------
    // Redirect: the single source of truth for auth-gated navigation.
    //
    // States:
    //   loading  → show '/'  (SplashScreen) while Supabase reads storage
    //   no session → force '/auth'
    //   has session → let the route through; block back-navigation to '/auth'
    // -------------------------------------------------------------------------
    redirect: (context, state) {
      // Still loading the auth stream — stay on splash
      if (authState.isLoading) {
        return state.matchedLocation == '/' ? null : '/';
      }

      // PASSWORD_RECOVERY deep link: always send to the update-password screen.
      // This gate runs before the normal isLoggedIn check because a recovery
      // session is technically "logged in" but should not reach a dashboard.
      if (isPasswordRecovery) {
        return state.matchedLocation == '/update-password' ? null : '/update-password';
      }

      final session = authState.valueOrNull?.session;
      final isLoggedIn = session != null;
      final isOnAuthPage = state.matchedLocation == '/auth' ||
          state.matchedLocation == '/' ||
          state.matchedLocation == '/onboarding' ||
          state.matchedLocation == '/safety_disclaimer' ||
          state.matchedLocation == '/update-password';

      // Not logged in and trying to access a protected route → kick to /auth
      if (!isLoggedIn && !isOnAuthPage) return '/auth';

      // Logged in but stuck on an auth/splash page → redirect to splash
      // which will resolve the correct dashboard via _checkSession()
      if (isLoggedIn && (state.matchedLocation == '/auth' ||
          state.matchedLocation == '/onboarding' ||
          state.matchedLocation == '/safety_disclaimer')) return '/';

      return null; // No redirect needed
    },
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
          path: '/doctor_rejected',
          builder: (context, state) => const DoctorRejectedScreen()),
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
            doctorId: extra['doctorId'],
            title: extra['title'] ?? 'Chat',
            isCompleted: extra['isCompleted'] ?? false,
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
          final data = state.extra as Map<String, dynamic>;

          // --- Safe type extraction ---
          // baseAmount: callers may pass double, int, or String
          final baseAmountRaw = data['baseAmount'];
          final double baseAmount = baseAmountRaw is num
              ? baseAmountRaw.toDouble()
              : double.tryParse(baseAmountRaw?.toString() ?? '') ?? 0.0;

          // appointmentId: may arrive as int, String, or null
          final idRaw = data['appointmentId'];
          final int? appointmentId = idRaw is int
              ? idRaw
              : int.tryParse(idRaw?.toString() ?? '');

          // userId: same treatment
          final userIdRaw = data['userId'];
          final int? userId = userIdRaw is int
              ? userIdRaw
              : int.tryParse(userIdRaw?.toString() ?? '');

          // paystackReference: guard against non-String nullables
          final paystackReference = data['paystackReference']?.toString();

          return PaymentScreen(
            transactionType: data['transactionType'] as String,
            baseAmount: baseAmount,
            title: data['title'] as String,
            appointmentId: appointmentId,
            userId: userId,
            paystackReference: paystackReference,
          );
        },
      ),
      GoRoute(
        path: '/lab_scanner',
        builder: (context, state) => const LabScannerScreen(),
      ),
      GoRoute(
        path: '/payout_settings',
        builder: (context, state) => const PayoutSettingsScreen(),
      ),
      GoRoute(
        path: '/family_dashboard',
        builder: (context, state) => const FamilyDashboardScreen(),
      ),
      GoRoute(
        path: '/update-password',
        builder: (context, state) => const UpdatePasswordScreen(),
      ),
    ],
  );
});
