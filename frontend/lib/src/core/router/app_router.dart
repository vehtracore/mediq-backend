import 'package:flutter/foundation.dart';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart' hide User;
import '../../features/auth/data/auth_state_provider.dart';
import '../../features/auth/data/profile_exception.dart';
import '../../features/auth/data/shell_identity.dart';
import '../../features/auth/presentation/user_controller.dart';
import '../../features/auth/presentation/profile_recovery_view.dart';

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
final rootScaffoldMessengerKey = GlobalKey<ScaffoldMessengerState>();

// ---------------------------------------------------------------------------
// Role Provider — single source of truth for the current user's role.
//
// Strategy: prefer the authoritative profile, then Supabase metadata, then a
// user-ID-keyed cached role as a navigation hint. Backend authorization never
// trusts this UI role.
// ---------------------------------------------------------------------------
final resolvedRoleProvider = FutureProvider<String?>((ref) async {
  // Re-evaluate whenever the auth stream fires (sign-in, sign-out, refresh).
  final authAsync = ref.watch(supabaseAuthProvider);

  // Still loading the stream — propagate the loading state.
  if (authAsync.isLoading) return null;

  final session = Supabase.instance.client.auth.currentSession ??
      authAsync.valueOrNull?.session;
  if (session == null) return null; // Logged out.

  // Prefer the latest authoritative application profile when available.
  final profileAsync = ref.watch(userProvider);
  final profileRole = profileAsync.valueOrNull?.role;
  if (profileRole != null && profileRole.isNotEmpty) return profileRole;

  // Fast-path: role embedded in the Supabase JWT by the backend at sign-up.
  final metaRole = session.user.userMetadata?['role'] as String?;
  if (metaRole != null && metaRole.isNotEmpty) return metaRole;

  // A user-ID-keyed cached role is a navigation hint only. FastAPI remains
  // authoritative for every protected operation.
  final shell = await ref.watch(activeShellIdentityProvider.future);
  return shell?.role;
});

// Tracks whether the current session is a password-recovery flow.
// GoRouter reads this via redirect to send the user to /update-password
// instead of a normal dashboard.
final _isPasswordRecoveryProvider = StateProvider<bool>((ref) => false);

// Public alias consumed by the router provider (keeps ref.watch tidy).
final passwordRecoveryProvider = _isPasswordRecoveryProvider;

bool nextPasswordRecoveryState(bool current, AuthChangeEvent event) {
  if (event == AuthChangeEvent.passwordRecovery) return true;
  if (event == AuthChangeEvent.signedIn || event == AuthChangeEvent.signedOut) {
    return false;
  }
  return current;
}

String? authRedirectDecision({
  required String location,
  required bool authLoading,
  required bool passwordRecovery,
  required bool hasSession,
  required bool preserveAuthenticatedRoute,
  required bool roleLoading,
  required String? role,
}) {
  // Auth/profile restoration is not a navigation event. In particular, the
  // Supabase stream briefly loading during token restoration must not destroy
  // an authenticated nested route. The splash route can keep displaying while
  // cold-start restoration completes.
  if (authLoading) {
    return preserveAuthenticatedRoute || location == '/' ? null : '/';
  }
  if (passwordRecovery && hasSession) {
    return location == '/update-password' ? null : '/update-password';
  }

  const publicRoutes = {
    '/auth',
    '/login',
    '/onboarding',
    '/safety_disclaimer',
    '/update-password',
    '/doctor_register',
  };
  final isPublicRoute = publicRoutes.contains(location);

  if (!hasSession) {
    if (location == '/') return '/auth';
    return isPublicRoute ? null : '/auth';
  }

  if (roleLoading) {
    return preserveAuthenticatedRoute ||
            location == '/' ||
            location == '/doctor_register'
        ? null
        : '/';
  }

  if (role == null ||
      (role != 'doctor' && role != 'patient' && role != 'admin')) {
    // A transient profile failure is not evidence that an already-open route
    // became invalid. At cold start the user remains on the authenticated
    // recovery/splash route until an authoritative role is available.
    return preserveAuthenticatedRoute ||
            location == '/' ||
            location == '/doctor_register'
        ? null
        : '/';
  }

  if ((isPublicRoute || location == '/') &&
      location != '/update-password' &&
      location != '/doctor_register') {
    if (role == 'doctor') return '/doctor_home';
    if (role == 'admin') return '/admin_dashboard';
    return '/patient_home';
  }

  if (role == 'patient' &&
      (location == '/doctor_home' ||
          location == '/doctor_edit_profile' ||
          location == '/doctor_availability' ||
          location == '/payout_settings')) {
    return '/patient_home';
  }
  if (role == 'doctor' &&
      (location == '/patient_home' ||
          location == '/find_doctor' ||
          location == '/book_appointment' ||
          location == '/medical_history')) {
    return '/doctor_home';
  }

  return null;
}

bool shouldResumeDoctorRegistration(
    String? metadataRole, Object? profileError) {
  if (metadataRole != 'doctor' ||
      profileError is! ProfileAuthoritativeException) {
    return false;
  }
  final cause = profileError.cause;
  return cause is DioException &&
      (cause.response?.statusCode == 401 || cause.response?.statusCode == 404);
}

final goRouterProvider = Provider<GoRouter>((ref) {
  final refresh = _RouterRefreshNotifier();
  String? establishedAuthenticatedUserId;
  ref.onDispose(refresh.dispose);

  // Detect PASSWORD_RECOVERY events from the Supabase stream and set the flag.
  ref.listen<AsyncValue<AuthState>>(supabaseAuthProvider, (_, next) {
    next.whenData((state) {
      final notifier = ref.read(_isPasswordRecoveryProvider.notifier);
      notifier.state = nextPasswordRecoveryState(notifier.state, state.event);
    });
    refresh.notify();
  });
  ref.listen<AsyncValue<String?>>(resolvedRoleProvider, (_, __) {
    refresh.notify();
  });
  ref.listen<bool>(_isPasswordRecoveryProvider, (_, __) {
    refresh.notify();
  });

  return GoRouter(
    navigatorKey: rootNavigatorKey,
    initialLocation: '/',
    refreshListenable: refresh,
    // -------------------------------------------------------------------------
    // Redirect — strict role-enforcement auth gate.
    //
    // Decision tree:
    //   1. Auth stream still loading           → hold on '/' (SplashScreen)
    //   2. PASSWORD_RECOVERY event             → force '/update-password'
    //   3. No session                          → force '/auth'
    //   4. Session present, role still loading → hold on '/' (SplashScreen)
    //   5. Role resolved:
    //        doctor  → only /doctor_home and doctor-only paths allowed
    //        patient → only /patient_home and patient-only paths allowed
    //        admin   → /admin_dashboard
    //        unknown → authenticated restoration UI on '/'
    // -------------------------------------------------------------------------
    redirect: (context, state) {
      final authState = ref.read(supabaseAuthProvider);
      final roleAsync = ref.read(resolvedRoleProvider);
      final isPasswordRecovery = ref.read(_isPasswordRecoveryProvider);
      final loc = state.matchedLocation;
      final session = Supabase.instance.client.auth.currentSession ??
          authState.valueOrNull?.session;
      final resolvedRole = roleAsync.valueOrNull;
      final hasResolvedRole = resolvedRole == 'doctor' ||
          resolvedRole == 'patient' ||
          resolvedRole == 'admin';
      if (session != null && hasResolvedRole) {
        establishedAuthenticatedUserId = session.user.id;
      } else if (session == null && !authState.isLoading) {
        establishedAuthenticatedUserId = null;
      }
      final preserveAuthenticatedRoute =
          session != null && establishedAuthenticatedUserId == session.user.id;
      if (session != null &&
          shouldResumeDoctorRegistration(
            session.user.userMetadata?['role'] as String?,
            ref.read(userProvider).error,
          )) {
        return loc == '/doctor_register' ? null : '/doctor_register';
      }
      final decision = authRedirectDecision(
        location: loc,
        authLoading: authState.isLoading,
        passwordRecovery: isPasswordRecovery,
        hasSession: session != null,
        preserveAuthenticatedRoute: preserveAuthenticatedRoute,
        roleLoading: !roleAsync.hasValue && roleAsync.isLoading,
        role: resolvedRole,
      );
      if (kDebugMode && decision != null && decision != loc) {
        debugPrint(
          '[ROUTER] $loc -> $decision '
          '(authenticated=${session != null}, '
          'authLoading=${authState.isLoading}, '
          'roleLoading=${roleAsync.isLoading})',
        );
      }
      return decision;
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
          builder: (context, state) => PatientHomeScreen(
                initialTab:
                    state.uri.queryParameters['tab'] == 'schedule' ? 1 : 0,
              )),
      GoRoute(
          path: '/doctor_home',
          builder: (context, state) => DoctorHomeScreen(
                initialTab: switch (state.uri.queryParameters['tab']) {
                  'requests' => 1,
                  'schedule' => 2,
                  _ => 0,
                },
              )),
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
          builder: (context, state) => EmergencyScreen(
                emergencyRequestId: state.uri.queryParameters['activationId'],
              )),
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
        builder: (context, state) {
          final extra = state.extra is Map<String, dynamic>
              ? state.extra as Map<String, dynamic>
              : const <String, dynamic>{};
          return AiChatScreen(
            sourceSummaryId: extra['sourceSummaryId'] as String?,
            sourceSummaryUpdatedAt: extra['sourceSummaryUpdatedAt'] as String?,
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
          final passedUser = state.extra;
          if (passedUser is User) {
            return EditProfileScreen(user: passedUser);
          }
          return Consumer(
            builder: (context, ref, _) {
              final profile = ref.watch(userProvider);
              return profile.when(
                data: (user) => user == null
                    ? Scaffold(
                        body: AuthenticatedProfileRecoveryView(
                          error: StateError(
                            'Authenticated profile was unavailable.',
                          ),
                        ),
                      )
                    : EditProfileScreen(user: user),
                loading: () => const Scaffold(
                  body: AuthenticatedProfileRecoveryView(),
                ),
                error: (error, _) => Scaffold(
                  body: AuthenticatedProfileRecoveryView(error: error),
                ),
              );
            },
          );
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
          final int? appointmentId =
              idRaw is int ? idRaw : int.tryParse(idRaw?.toString() ?? '');

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

class _RouterRefreshNotifier extends ChangeNotifier {
  void notify() => notifyListeners();
}
