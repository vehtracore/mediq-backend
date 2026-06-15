import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart' hide User;
import '../../features/auth/data/auth_repository.dart';
import '../storage/storage_service.dart';

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
import '../../features/appointments/presentation/appointment_detail_screen.dart';

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

bool _sessionNeedsRefresh(Session session) {
  final expiresAt = session.expiresAt;
  if (expiresAt == null) return false;

  final expiry = DateTime.fromMillisecondsSinceEpoch(
    expiresAt * 1000,
    isUtc: true,
  );
  return expiry.isBefore(DateTime.now().toUtc().add(const Duration(minutes: 1)));
}

final sessionRestoreProvider = FutureProvider<bool>((ref) async {
  ref.watch(supabaseAuthProvider);

  final auth = Supabase.instance.client.auth;
  final storage = ref.read(storageServiceProvider);
  final currentSession = auth.currentSession;
  final storedRefreshToken = await storage.getRefreshToken();

  if (currentSession == null &&
      (storedRefreshToken == null || storedRefreshToken.isEmpty)) {
    return false;
  }

  if (currentSession != null && !_sessionNeedsRefresh(currentSession)) {
    await storage.saveToken(currentSession.accessToken);
    final refreshToken = currentSession.refreshToken;
    if (refreshToken != null && refreshToken.isNotEmpty) {
      await storage.saveRefreshToken(refreshToken);
    }
    return true;
  }

  final refreshToken = currentSession?.refreshToken ?? storedRefreshToken;
  if (refreshToken == null || refreshToken.isEmpty) {
    await storage.deleteToken();
    return false;
  }

  try {
    final response = await auth.refreshSession(refreshToken);
    final refreshedSession = response.session ?? auth.currentSession;
    if (refreshedSession == null) {
      await storage.deleteToken();
      return false;
    }

    await storage.saveToken(refreshedSession.accessToken);
    final refreshedToken = refreshedSession.refreshToken;
    if (refreshedToken != null && refreshedToken.isNotEmpty) {
      await storage.saveRefreshToken(refreshedToken);
    }
    return true;
  } catch (_) {
    await auth.signOut();
    await storage.deleteToken();
    return false;
  }
});

// ---------------------------------------------------------------------------
// Role Provider — single source of truth for the current user's role.
//
// Strategy (fast-path first, no unnecessary network calls):
//   1. Read role from the Supabase JWT user_metadata synchronously.  This is
//      populated by the backend on register and is present in the cached
//      session — zero latency, works offline.
//   2. If the JWT metadata has no role (legacy accounts), fall back to a
//      backend call to /api/v1/auth/me.
//   3. Returns null when there is no active session.
// ---------------------------------------------------------------------------
final resolvedRoleProvider = FutureProvider<String?>((ref) async {
  // Re-evaluate whenever the auth stream fires (sign-in, sign-out, refresh).
  final authAsync = ref.watch(supabaseAuthProvider);
  final sessionReady = ref.watch(sessionRestoreProvider);

  // Still loading the stream — propagate the loading state.
  if (authAsync.isLoading) return null;
  if (sessionReady.isLoading || sessionReady.valueOrNull != true) return null;

  final session =
      Supabase.instance.client.auth.currentSession ?? authAsync.valueOrNull?.session;
  if (session == null) return null; // Logged out.

  // Fast-path: role embedded in the Supabase JWT by the backend at sign-up.
  final metaRole = session.user.userMetadata?['role'] as String?;
  if (metaRole != null && metaRole.isNotEmpty) return metaRole;

  // Slow-path: fetch from the backend profile endpoint (legacy / edge-case).
  try {
    final repo = ref.read(authRepositoryProvider);
    final user = await repo.getUserProfile();
    return user?.role;
  } catch (_) {
    return null; // Backend unreachable — treat as unresolved.
  }
});

// Tracks whether the current session is a password-recovery flow.
// GoRouter reads this via redirect to send the user to /update-password
// instead of a normal dashboard.
final _isPasswordRecoveryProvider = StateProvider<bool>((ref) => false);

// Public alias consumed by the router provider (keeps ref.watch tidy).
final passwordRecoveryProvider = _isPasswordRecoveryProvider;

final goRouterProvider = Provider<GoRouter>((ref) {
  // Watch both the auth stream AND the resolved role so GoRouter rebuilds
  // on every session change AND whenever the role finishes loading.
  final authState = ref.watch(supabaseAuthProvider);
  final sessionRestore = ref.watch(sessionRestoreProvider);
  final roleAsync = ref.watch(resolvedRoleProvider);

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
    // Redirect — strict role-enforcement auth gate.
    //
    // Decision tree:
    //   1. Auth/session restore still loading  → hold on '/' (SplashScreen)
    //   2. PASSWORD_RECOVERY event             → force '/update-password'
    //   3. No session                          → force '/auth'
    //   4. Session present, role still loading → hold on '/' (SplashScreen)
    //   5. Role resolved:
    //        doctor  → only /doctor_home and doctor-only paths allowed
    //        patient → only /patient_home and patient-only paths allowed
    //        admin   → /admin_dashboard
    //        unknown → '/auth' (cannot determine role — treat as unauthenticated)
    // -------------------------------------------------------------------------
    redirect: (context, state) {
      final loc = state.matchedLocation;

      // ── Step 1: Supabase session stream still initialising ────────────────
      if (authState.isLoading || sessionRestore.isLoading) {
        return loc == '/' ? null : '/';
      }

      // ── Step 2: Password-recovery deep link ──────────────────────────────
      if (isPasswordRecovery) {
        return loc == '/update-password' ? null : '/update-password';
      }

      final session = authState.valueOrNull?.session;
      final isLoggedIn = session != null;

      // Public routes — accessible without a session.
      const publicRoutes = {
        '/auth',
        '/login',
        '/',
        '/onboarding',
        '/safety_disclaimer',
        '/update-password',
        '/doctor_register',
      };
      final isPublicRoute = publicRoutes.contains(loc);

      // ── Step 3: No session → kick to /auth ───────────────────────────────
      final hasRestoredSession = sessionRestore.valueOrNull == true;

      if (!isLoggedIn || !hasRestoredSession) {
        return isPublicRoute ? null : '/login';
      }

      // ── Step 4: Session exists but role not yet resolved ─────────────────
      // Keep the user on the splash screen until we know their role so we
      // never accidentally drop them on the wrong dashboard.
      if (roleAsync.isLoading || (!roleAsync.hasValue && !roleAsync.hasError)) {
        return loc == '/' ? null : '/';
      }

      // ── Step 5: Role resolved — enforce strict routing ───────────────────
      final role = roleAsync.valueOrNull;

      // Could not determine role (backend error / unknown role string).
      // Clear session-aware state and bounce to /auth.
      if (role == null || (role != 'doctor' && role != 'patient' && role != 'admin')) {
        // Only redirect away from public routes to avoid infinite loops.
        return isPublicRoute ? null : '/login';
      }

      // Logged-in user landing on a public/splash page → send to their home.
      if (isPublicRoute && loc != '/update-password' && loc != '/doctor_register') {
        if (role == 'doctor') return '/doctor_home';
        if (role == 'admin') return '/admin_dashboard';
        return '/patient_home';
      }

      // ── Cross-role contamination guard ───────────────────────────────────
      // A doctor must never reach the patient dashboard and vice-versa.
      // Patient trying to reach doctor routes → patient home.
      if (role == 'patient' && (loc == '/doctor_home' ||
          loc == '/doctor_edit_profile' ||
          loc == '/doctor_availability' ||
          loc == '/payout_settings')) {
        return '/patient_home';
      }
      // Doctor trying to reach patient-only routes → doctor home.
      if (role == 'doctor' && (loc == '/patient_home' ||
          loc == '/find_doctor' ||
          loc == '/book_appointment' ||
          loc == '/medical_history')) {
        return '/doctor_home';
      }

      return null; // Route is valid for this role — allow.
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
      GoRoute(path: '/login', builder: (context, state) => const AuthScreen()),
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
        path: '/appointment/:id',
        builder: (context, state) {
          final idString = state.pathParameters['id'];
          final appointmentId = int.tryParse(idString ?? '') ?? 0;
          return AppointmentDetailScreen(appointmentId: appointmentId);
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
