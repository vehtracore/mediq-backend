import 'package:flutter_test/flutter_test.dart';
import 'package:mediq_app/src/core/router/app_router.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

String? _redirect({
  String location = '/patient_home',
  bool authLoading = false,
  bool passwordRecovery = false,
  bool hasSession = true,
  bool roleLoading = false,
  String? role = 'patient',
}) {
  return authRedirectDecision(
    location: location,
    authLoading: authLoading,
    passwordRecovery: passwordRecovery,
    hasSession: hasSession,
    roleLoading: roleLoading,
    role: role,
  );
}

void main() {
  test('authenticated profile loading is held on restoration, not auth', () {
    expect(_redirect(roleLoading: true), '/');
    expect(_redirect(location: '/', roleLoading: true), isNull);
  });

  test('authenticated unresolved/profile-failure role stays on restoration',
      () {
    expect(_redirect(role: null), '/');
    expect(_redirect(location: '/', role: null), isNull);
  });

  test('only a genuinely absent session routes to auth', () {
    expect(_redirect(hasSession: false), '/auth');
  });

  test('password recovery unlatches on completion sign-out and later login',
      () {
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
}
