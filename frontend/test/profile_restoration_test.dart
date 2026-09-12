import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mediq_app/src/features/auth/data/auth_repository.dart';
import 'package:mediq_app/src/features/auth/data/auth_session_coordinator.dart';
import 'package:mediq_app/src/features/auth/data/auth_state_provider.dart';
import 'package:mediq_app/src/features/auth/data/profile_exception.dart';
import 'package:mediq_app/src/features/auth/data/shell_identity.dart';
import 'package:mediq_app/src/features/auth/data/user_model.dart';
import 'package:mediq_app/src/features/auth/presentation/profile_recovery_view.dart';
import 'package:mediq_app/src/features/auth/presentation/user_controller.dart';

class _MemoryShellStore implements ShellIdentityStore {
  final Map<String, ShellIdentity> values = {};

  @override
  Future<ShellIdentity?> read(String userId) async => values[userId];

  @override
  Future<void> remove(String userId) async => values.remove(userId);

  @override
  Future<void> write(ShellIdentity identity) async {
    values[identity.userId] = identity;
  }
}

class _SequenceAuthRepository extends AuthRepository {
  _SequenceAuthRepository(this.results) : super(Dio());

  final List<Object> results;
  int calls = 0;

  @override
  Future<User?> getUserProfile() async {
    final result = results[calls++];
    if (result is User) return result;
    throw result;
  }
}

class _DelayedAuthRepository extends AuthRepository {
  _DelayedAuthRepository(this.profile) : super(Dio());

  final Future<User?> profile;

  @override
  Future<User?> getUserProfile() => profile;
}

class _SessionGateway implements AuthSessionGateway {
  _SessionGateway(this.session, this.refreshed);

  AuthSessionSnapshot? session;
  final AuthSessionSnapshot refreshed;
  int signOutCalls = 0;

  @override
  AuthSessionSnapshot? get currentSession => session;

  @override
  Future<AuthSessionSnapshot> refreshSession() async {
    session = refreshed;
    return refreshed;
  }

  @override
  Future<void> signOut() async {
    signOutCalls += 1;
    session = null;
  }
}

User _user(String name) => User(
      id: '42',
      email: 'person@example.test',
      firstName: name,
      lastName: 'Okafor',
      role: 'patient',
    );

Dio _respondingDio(Object data, {int statusCode = 200}) {
  final dio = Dio();
  dio.interceptors.add(
    InterceptorsWrapper(
      onRequest: (options, handler) {
        final response = Response<dynamic>(
          requestOptions: options,
          statusCode: statusCode,
          data: data,
        );
        if (statusCode >= 400) {
          handler.reject(
            DioException.badResponse(
              statusCode: statusCode,
              requestOptions: options,
              response: response,
            ),
          );
        } else {
          handler.resolve(response);
        }
      },
    ),
  );
  return dio;
}

void main() {
  test(
      'Scenario A: stale persisted token refreshes before delayed profile and name resolves',
      () async {
    final now = DateTime.utc(2026, 9, 5);
    final gateway = _SessionGateway(
      AuthSessionSnapshot(
        accessToken: 'expired',
        userId: 'supabase-a',
        expiresAt: now.subtract(const Duration(minutes: 1)),
      ),
      AuthSessionSnapshot(
        accessToken: 'fresh',
        userId: 'supabase-a',
        expiresAt: now.add(const Duration(hours: 1)),
      ),
    );
    final profileCompleter = Completer<User?>();
    final store = _MemoryShellStore();
    final container = ProviderContainer(
      overrides: [
        authUserIdProvider.overrideWith((ref) => 'supabase-a'),
        authRepositoryProvider.overrideWithValue(
          _DelayedAuthRepository(profileCompleter.future),
        ),
        shellIdentityStoreProvider.overrideWithValue(store),
      ],
    );
    addTearDown(container.dispose);

    final coordinator =
        AuthSessionCoordinator(gateway: gateway, now: () => now);
    expect(await coordinator.accessTokenIfAvailable(), 'fresh');
    final loadingProfile = container.read(userProvider.future);
    expect(gateway.signOutCalls, 0);

    profileCompleter.complete(_user('Ada'));
    expect((await loadingProfile)?.firstName, 'Ada');
    expect(store.values['supabase-a']?.displayName, 'Ada Okafor');
  });

  test('valid session profile success caches the correct displayed identity',
      () async {
    final store = _MemoryShellStore();
    final repository = _SequenceAuthRepository([_user('Ada')]);
    final container = ProviderContainer(
      overrides: [
        authUserIdProvider.overrideWith((ref) => 'supabase-a'),
        authRepositoryProvider.overrideWithValue(repository),
        shellIdentityStoreProvider.overrideWithValue(store),
      ],
    );
    addTearDown(container.dispose);

    final user = await container.read(userProvider.future);
    expect(user?.firstName, 'Ada');
    expect(store.values['supabase-a']?.displayName, 'Ada Okafor');
  });

  test(
      'Scenario B: offline profile preserves cached shell and retry repairs UI',
      () async {
    final store = _MemoryShellStore()
      ..values['supabase-a'] = const ShellIdentity(
        userId: 'supabase-a',
        displayName: 'Ada Okafor',
        role: 'patient',
      );
    final repository = _SequenceAuthRepository([
      const ProfileTemporaryException('offline'),
      _user('Ada'),
    ]);
    final container = ProviderContainer(
      overrides: [
        authUserIdProvider.overrideWith((ref) => 'supabase-a'),
        authRepositoryProvider.overrideWithValue(repository),
        shellIdentityStoreProvider.overrideWithValue(store),
      ],
    );
    addTearDown(container.dispose);

    await expectLater(
      container.read(userProvider.future),
      throwsA(isA<ProfileTemporaryException>()),
    );
    expect((await store.read('supabase-a'))?.displayName, 'Ada Okafor');

    container.invalidate(userProvider);
    expect((await container.read(userProvider.future))?.firstName, 'Ada');
    expect(repository.calls, 2);
  });

  test('profile parsing, backend 5xx, and final 401 retain explicit semantics',
      () async {
    await expectLater(
      AuthRepository(_respondingDio('not-an-object')).getCurrentUser(),
      throwsA(isA<ProfileTemporaryException>()),
    );
    await expectLater(
      AuthRepository(_respondingDio(<String, dynamic>{})).getCurrentUser(),
      throwsA(isA<ProfileAuthoritativeException>()),
    );
    await expectLater(
      AuthRepository(_respondingDio({}, statusCode: 503)).getCurrentUser(),
      throwsA(isA<ProfileTemporaryException>()),
    );
    await expectLater(
      AuthRepository(_respondingDio({}, statusCode: 401)).getCurrentUser(),
      throwsA(isA<ProfileAuthoritativeException>()),
    );
  });

  test(
      'Scenario C: temporary backend failure keeps recovery possible without login',
      () async {
    final store = _MemoryShellStore();
    final repository = _SequenceAuthRepository([
      const ProfileTemporaryException('backend unavailable'),
      _user('Ada'),
    ]);
    final container = ProviderContainer(
      overrides: [
        authUserIdProvider.overrideWith((ref) => 'supabase-a'),
        authRepositoryProvider.overrideWithValue(repository),
        shellIdentityStoreProvider.overrideWithValue(store),
      ],
    );
    addTearDown(container.dispose);

    await expectLater(
      container.read(userProvider.future),
      throwsA(isA<ProfileTemporaryException>()),
    );
    container.invalidate(userProvider);
    expect((await container.read(userProvider.future))?.firstName, 'Ada');
  });

  test(
      'Account A shell cannot appear under Account B and logout removal clears it',
      () async {
    final store = _MemoryShellStore();
    await store.write(const ShellIdentity(
      userId: 'account-a',
      displayName: 'Account A',
      role: 'patient',
    ));

    expect(await store.read('account-b'), isNull);
    await clearShellIdentityForUser(store, 'account-a');
    expect(await store.read('account-a'), isNull);
  });

  testWidgets(
      'temporary profile state is controlled and never renders question-mark avatar',
      (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          activeShellIdentityProvider.overrideWith((ref) async {
            return const ShellIdentity(
              userId: 'account-a',
              displayName: 'Ada Okafor',
              role: 'patient',
            );
          }),
        ],
        child: const MaterialApp(
          home: Scaffold(
            body: AuthenticatedProfileRecoveryView(
              error: ProfileTemporaryException('offline'),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Ada Okafor'), findsOneWidget);
    expect(find.text('Retry profile'), findsOneWidget);
    expect(find.text('?'), findsNothing);
  });
}
