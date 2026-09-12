import 'package:flutter_test/flutter_test.dart';
import 'package:mediq_app/src/features/auth/data/auth_session_coordinator.dart';
import 'package:mediq_app/src/features/chat/data/websocket_auth_retry.dart';

class _Gateway implements AuthSessionGateway {
  _Gateway(this.session, this.refreshed);

  AuthSessionSnapshot? session;
  final AuthSessionSnapshot refreshed;
  int refreshCalls = 0;

  @override
  AuthSessionSnapshot? get currentSession => session;

  @override
  Future<AuthSessionSnapshot> refreshSession() async {
    refreshCalls += 1;
    session = refreshed;
    return refreshed;
  }

  @override
  Future<void> signOut() async => session = null;
}

void main() {
  test('socket auth expiry can claim one reconnect maximum', () {
    final gate = WebSocketAuthRetryGate();

    expect(gate.claim(4401), isTrue);
    expect(gate.claim(4401), isFalse);
    expect(gate.attempted, isTrue);
  });

  test('non-auth socket closure never consumes retry', () {
    final gate = WebSocketAuthRetryGate();

    expect(gate.claim(1000), isFalse);
    expect(gate.attempted, isFalse);
    expect(gate.claim(4401), isTrue);
  });

  test('socket obtains a refreshed token before connection', () async {
    final now = DateTime.utc(2026, 9, 5);
    final gateway = _Gateway(
      AuthSessionSnapshot(
        accessToken: 'expired',
        userId: 'account-a',
        expiresAt: now.subtract(const Duration(minutes: 1)),
      ),
      AuthSessionSnapshot(
        accessToken: 'fresh',
        userId: 'account-a',
        expiresAt: now.add(const Duration(hours: 1)),
      ),
    );
    final auth = CoordinatedWebSocketAuth(
      AuthSessionCoordinator(gateway: gateway, now: () => now),
    );

    expect(await auth.tokenForConnection(), 'fresh');
    expect(gateway.refreshCalls, 1);
  });

  test('coordinated socket recovery runs at most once', () async {
    final now = DateTime.utc(2026, 9, 5);
    final gateway = _Gateway(
      AuthSessionSnapshot(
        accessToken: 'rejected',
        userId: 'account-a',
        expiresAt: now.add(const Duration(hours: 1)),
      ),
      AuthSessionSnapshot(
        accessToken: 'fresh',
        userId: 'account-a',
        expiresAt: now.add(const Duration(hours: 2)),
      ),
    );
    final auth = CoordinatedWebSocketAuth(
      AuthSessionCoordinator(gateway: gateway, now: () => now),
    );

    expect(
      await auth.recoverOnce(
        closeCode: 4401,
        rejectedAccessToken: 'rejected',
      ),
      isTrue,
    );
    expect(
      await auth.recoverOnce(
        closeCode: 4401,
        rejectedAccessToken: 'rejected',
      ),
      isFalse,
    );
    expect(gateway.refreshCalls, 1);
  });
}
