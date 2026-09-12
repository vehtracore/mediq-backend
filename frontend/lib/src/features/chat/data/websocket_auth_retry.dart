import '../../auth/data/auth_session_coordinator.dart';

class WebSocketAuthRetryGate {
  bool _attempted = false;

  bool claim(int? closeCode) {
    if (closeCode != 4401 || _attempted) return false;
    _attempted = true;
    return true;
  }

  bool get attempted => _attempted;
}

class CoordinatedWebSocketAuth {
  CoordinatedWebSocketAuth(
    this._coordinator, {
    WebSocketAuthRetryGate? retryGate,
  }) : _retryGate = retryGate ?? WebSocketAuthRetryGate();

  final AuthSessionCoordinator _coordinator;
  final WebSocketAuthRetryGate _retryGate;

  Future<String> tokenForConnection() async {
    final token = await _coordinator.accessTokenIfAvailable();
    if (token == null || token.isEmpty) {
      throw const AuthSessionUnavailableException();
    }
    return token;
  }

  Future<bool> recoverOnce({
    required int? closeCode,
    required String rejectedAccessToken,
  }) async {
    if (!_retryGate.claim(closeCode)) return false;
    await _coordinator.recoverAfterUnauthorized(rejectedAccessToken);
    return true;
  }
}
