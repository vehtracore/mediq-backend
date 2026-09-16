import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mediq_app/src/core/router/app_router.dart';
import 'package:mediq_app/src/features/auth/data/profile_exception.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

String? _redirect({
  String location = '/patient_home',
  bool authLoading = false,
  bool passwordRecovery = false,
  bool hasSession = true,
  bool preserveAuthenticatedRoute = true,
  bool roleLoading = false,
  String? role = 'patient',
}) {
  return authRedirectDecision(
    location: location,
    authLoading: authLoading,
    passwordRecovery: passwordRecovery,
    hasSession: hasSession,
    preserveAuthenticatedRoute: preserveAuthenticatedRoute,
    roleLoading: roleLoading,
    role: role,
  );
}

void main() {
  test('authenticated profile loading preserves an existing feature route', () {
    expect(_redirect(location: '/ai-chat', roleLoading: true), isNull);
    expect(_redirect(location: '/emergency', roleLoading: true), isNull);
    expect(_redirect(location: '/', roleLoading: true), isNull);
  });

  test('authenticated unresolved/profile-failure role preserves navigation',
      () {
    expect(_redirect(location: '/video_call', role: null), isNull);
    expect(_redirect(location: '/', role: null), isNull);
  });

  test('auth stream restoration does not redirect a nested route', () {
    expect(_redirect(location: '/ai-chat', authLoading: true), isNull);
  });

  test('cold-start unresolved deep link remains behind restoration', () {
    expect(
      _redirect(
        location: '/ai-chat',
        roleLoading: true,
        preserveAuthenticatedRoute: false,
      ),
      '/',
    );
  });

  test('only a genuinely absent session routes to auth', () {
    expect(_redirect(hasSession: false), '/auth');
    expect(
      _redirect(location: '/ai-chat', hasSession: false),
      '/auth',
    );
  });

  test('resolved role restrictions still correct invalid routes', () {
    expect(
      _redirect(location: '/doctor_home', role: 'patient'),
      '/patient_home',
    );
  });

  test('password recovery unlatches on completion sign-out and later login',
      () {
    expect(_redirect(passwordRecovery: true), '/update-password');
    expect(
      _redirect(passwordRecovery: true, hasSession: false),
      '/auth',
    );
    var recovery = nextPasswordRecoveryState(
      false,
      AuthChangeEvent.passwordRecovery,
    );
    expect(recovery, isTrue);

    recovery = nextPasswordRecoveryState(recovery, AuthChangeEvent.signedOut);
    expect(recovery, isFalse);
    expect(
      nextPasswordRecoveryState(recovery, AuthChangeEvent.signedIn),
      isFalse,
    );
  });

  test(
      'verified doctor identity with no local application resumes registration',
      () {
    final request = RequestOptions(path: '/api/v1/auth/me');
    final missingProfile = ProfileAuthoritativeException(
      'Profile not found',
      cause: DioException(
        requestOptions: request,
        response: Response(requestOptions: request, statusCode: 401),
      ),
    );
    expect(shouldResumeDoctorRegistration('doctor', missingProfile), isTrue);
    expect(shouldResumeDoctorRegistration('patient', missingProfile), isFalse);
    expect(
      shouldResumeDoctorRegistration(
        'doctor',
        const ProfileTemporaryException('Network unavailable'),
      ),
      isFalse,
    );
  });
}
