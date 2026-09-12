import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mediq_app/src/features/auth/data/shell_identity.dart';
import 'package:mediq_app/src/features/auth/data/user_model.dart';
import 'package:mediq_app/src/features/auth/presentation/auth_session_lifecycle.dart';
import 'package:mediq_app/src/features/auth/presentation/user_controller.dart';
import 'package:supabase_flutter/supabase_flutter.dart' hide User;

class _Store implements ShellIdentityStore {
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

void main() {
  test('explicit teardown clears profile and account-keyed shell identity',
      () async {
    final store = _Store()
      ..values['account-a'] = const ShellIdentity(
        userId: 'account-a',
        displayName: 'Account A',
        role: 'patient',
      );
    final trigger = Provider<Future<void>>(
      (ref) => clearAuthenticatedUserState(ref, 'account-a'),
    );
    final container = ProviderContainer(
      overrides: [shellIdentityStoreProvider.overrideWithValue(store)],
    );
    addTearDown(container.dispose);
    container.read(userControllerProvider.notifier).setUser(
          User(
            id: '1',
            email: 'a@example.test',
            firstName: 'Account',
            lastName: 'A',
            role: 'patient',
          ),
        );

    await container.read(trigger);

    expect(container.read(userControllerProvider).value, isNull);
    expect(await store.read('account-a'), isNull);
  });

  test('account switch identifies only the former account for teardown', () {
    final tracker = SessionUserTransitionTracker();

    expect(tracker.observe(AuthChangeEvent.signedIn, 'account-a'), isNull);
    expect(
      tracker.observe(AuthChangeEvent.signedIn, 'account-b'),
      'account-a',
    );
    expect(
        tracker.observe(AuthChangeEvent.tokenRefreshed, 'account-b'), isNull);
    expect(tracker.observe(AuthChangeEvent.signedOut, null), 'account-b');
  });
}
