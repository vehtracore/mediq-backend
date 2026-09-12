import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:mediq_app/src/features/auth/data/auth_session_coordinator.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

class _FakeGateway implements AuthSessionGateway {
  AuthSessionSnapshot? session;
  Future<AuthSessionSnapshot> Function()? onRefresh;
  int refreshCalls = 0;
  int signOutCalls = 0;

  @override
  AuthSessionSnapshot? get currentSession => session;

  @override
  Future<AuthSessionSnapshot> refreshSession() async {
    refreshCalls += 1;
    final refreshed = await onRefresh!();
    session = refreshed;
    return refreshed;
  }

  @override
  Future<void> signOut() async {
    signOutCalls += 1;
    session = null;
  }
}

AuthSessionSnapshot _session(
  DateTime now, {
  required String token,
  required Duration expiresIn,
}) {
  return AuthSessionSnapshot(
    accessToken: token,
    userId: 'account-a',
    expiresAt: now.add(expiresIn),
  );
}

void main() {
  final now = DateTime.utc(2026, 9, 5, 10);

  test('valid persisted token survives restart without refresh', () async {
    final gateway = _FakeGateway()
      ..session =
          _session(now, token: 'valid', expiresIn: const Duration(minutes: 10));
    final coordinator =
        AuthSessionCoordinator(gateway: gateway, now: () => now);

    expect(await coordinator.accessTokenIfAvailable(), 'valid');
    expect(gateway.refreshCalls, 0);
    expect(gateway.signOutCalls, 0);
  });

  for (final scenario in <String, Duration>{
    'near-expiry token refreshes before use': const Duration(seconds: 30),
    'expired persisted token survives restart with valid refresh':
        const Duration(minutes: -1),
    'two-hour background return refreshes and remains authenticated':
        const Duration(hours: -2),
    'next-day restoration refreshes when the refresh session remains valid':
        const Duration(days: -1),
  }.entries) {
    test(scenario.key, () async {
      final refreshed =
          _session(now, token: 'new', expiresIn: const Duration(hours: 1));
      final gateway = _FakeGateway()
        ..session = _session(now, token: 'old', expiresIn: scenario.value)
        ..onRefresh = () async => refreshed;
      final coordinator =
          AuthSessionCoordinator(gateway: gateway, now: () => now);

      expect(await coordinator.accessTokenIfAvailable(), 'new');
      expect(gateway.refreshCalls, 1);
      expect(gateway.signOutCalls, 0);
    });
  }

  test('concurrent expired-token requests share exactly one refresh', () async {
    final completer = Completer<AuthSessionSnapshot>();
    final gateway = _FakeGateway()
      ..session =
          _session(now, token: 'old', expiresIn: const Duration(minutes: -1))
      ..onRefresh = () => completer.future;
    final coordinator =
        AuthSessionCoordinator(gateway: gateway, now: () => now);

    final requests =
        List.generate(4, (_) => coordinator.accessTokenIfAvailable());
    await Future<void>.delayed(Duration.zero);
    expect(gateway.refreshCalls, 1);

    completer.complete(
        _session(now, token: 'shared', expiresIn: const Duration(hours: 1)));
    expect(await Future.wait(requests), everyElement('shared'));
  });

  test('transient refresh failure preserves session and unlocks later retry',
      () async {
    var fail = true;
    final gateway = _FakeGateway()
      ..session =
          _session(now, token: 'old', expiresIn: const Duration(minutes: -1))
      ..onRefresh = () async {
        if (fail) throw AuthRetryableFetchException(message: 'offline');
        return _session(now,
            token: 'recovered', expiresIn: const Duration(hours: 1));
      };
    final coordinator =
        AuthSessionCoordinator(gateway: gateway, now: () => now);

    await expectLater(
      coordinator.accessTokenIfAvailable(),
      throwsA(isA<TransientSessionRefreshException>()),
    );
    expect(gateway.signOutCalls, 0);
    expect(gateway.session, isNotNull);

    fail = false;
    expect(await coordinator.accessTokenIfAvailable(), 'recovered');
    expect(gateway.refreshCalls, 2);
  });

  test('terminal Supabase refresh failure signs out', () async {
    final gateway = _FakeGateway()
      ..session =
          _session(now, token: 'old', expiresIn: const Duration(minutes: -1))
      ..onRefresh = () async => throw AuthApiException(
            'refresh token revoked',
            statusCode: '400',
          );
    final coordinator =
        AuthSessionCoordinator(gateway: gateway, now: () => now);

    await expectLater(
      coordinator.accessTokenIfAvailable(),
      throwsA(isA<TerminalSessionRefreshException>()),
    );
    expect(gateway.signOutCalls, 1);
    expect(gateway.session, isNull);
  });

  test('explicit logout wins over an in-flight refresh and later login works',
      () async {
    final completer = Completer<AuthSessionSnapshot>();
    final gateway = _FakeGateway()
      ..session = _session(
        now,
        token: 'old',
        expiresIn: const Duration(minutes: -1),
      )
      ..onRefresh = () => completer.future;
    final coordinator =
        AuthSessionCoordinator(gateway: gateway, now: () => now);

    final waitingRequest = coordinator.accessTokenIfAvailable();
    await Future<void>.delayed(Duration.zero);
    final logout = coordinator.signOutExplicitly();
    completer.complete(
      _session(now, token: 'refreshed', expiresIn: const Duration(hours: 1)),
    );

    await expectLater(
      waitingRequest,
      throwsA(isA<AuthSessionUnavailableException>()),
    );
    await logout;
    expect(gateway.signOutCalls, 1);
    expect(gateway.session, isNull);

    gateway.session = _session(now,
        token: 'later-login', expiresIn: const Duration(hours: 1));
    expect(await coordinator.accessTokenIfAvailable(), 'later-login');
  });
}
