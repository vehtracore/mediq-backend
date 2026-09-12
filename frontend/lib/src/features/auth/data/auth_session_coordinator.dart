import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

/// The small portion of a Supabase session needed by authenticated transports.
/// Refresh tokens deliberately never leave the SDK gateway.
class AuthSessionSnapshot {
  const AuthSessionSnapshot({
    required this.accessToken,
    required this.userId,
    required this.expiresAt,
  });

  final String accessToken;
  final String userId;
  final DateTime? expiresAt;
}

abstract class AuthSessionGateway {
  AuthSessionSnapshot? get currentSession;

  Future<AuthSessionSnapshot> refreshSession();

  Future<void> signOut();
}

class SupabaseAuthSessionGateway implements AuthSessionGateway {
  SupabaseAuthSessionGateway(this._client);

  final SupabaseClient _client;

  @override
  AuthSessionSnapshot? get currentSession =>
      _snapshot(_client.auth.currentSession);

  @override
  Future<AuthSessionSnapshot> refreshSession() async {
    final response = await _client.auth.refreshSession();
    final snapshot = _snapshot(response.session);
    if (snapshot == null) {
      throw AuthSessionMissingException();
    }
    return snapshot;
  }

  @override
  Future<void> signOut() => _client.auth.signOut();

  static AuthSessionSnapshot? _snapshot(Session? session) {
    if (session == null) return null;
    final expiresAt = session.expiresAt;
    return AuthSessionSnapshot(
      accessToken: session.accessToken,
      userId: session.user.id,
      expiresAt: expiresAt == null
          ? null
          : DateTime.fromMillisecondsSinceEpoch(expiresAt * 1000, isUtc: true),
    );
  }
}

class AuthSessionUnavailableException implements Exception {
  const AuthSessionUnavailableException();
}

class TransientSessionRefreshException implements Exception {
  const TransientSessionRefreshException(this.cause);

  final Object cause;
}

class TerminalSessionRefreshException implements Exception {
  const TerminalSessionRefreshException(this.cause);

  final Object cause;
}

/// Provides request-time access-token freshness and one shared refresh Future.
class AuthSessionCoordinator {
  AuthSessionCoordinator({
    required AuthSessionGateway gateway,
    DateTime Function()? now,
    this.safetyWindow = const Duration(seconds: 45),
  })  : _gateway = gateway,
        _now = now ?? DateTime.now;

  final AuthSessionGateway _gateway;
  final DateTime Function() _now;
  final Duration safetyWindow;

  Future<AuthSessionSnapshot>? _refreshInFlight;
  bool _explicitSignOutPending = false;
  bool _explicitlySignedOut = false;

  AuthSessionSnapshot? get currentSession => _gateway.currentSession;

  bool isFresh(AuthSessionSnapshot session) {
    final expiry = session.expiresAt;
    return expiry != null && expiry.isAfter(_now().toUtc().add(safetyWindow));
  }

  /// Returns null only when there is no Supabase session.
  Future<String?> accessTokenIfAvailable() async {
    final session = currentSession;
    if (session == null) return null;
    if (_explicitSignOutPending) return null;
    if (_explicitlySignedOut) {
      // A non-null session after explicit sign-out can only be a later login.
      _explicitlySignedOut = false;
    }
    if (isFresh(session)) {
      _log('token valid');
      return session.accessToken;
    }

    _log(session.expiresAt?.isAfter(_now().toUtc()) == true
        ? 'token near expiry'
        : 'token expired');
    final refreshed = await _refreshSingleFlight();
    if (_explicitSignOutPending) {
      throw const AuthSessionUnavailableException();
    }
    return refreshed.accessToken;
  }

  /// Recovers from a backend 401 without assuming that the backend owns the
  /// Supabase session. If auto-refresh already replaced the rejected token,
  /// the new current token is reused without another refresh.
  Future<String> recoverAfterUnauthorized(String? rejectedAccessToken) async {
    final current = currentSession;
    if (current == null || _explicitSignOutPending || _explicitlySignedOut) {
      throw const AuthSessionUnavailableException();
    }

    if (rejectedAccessToken != null &&
        current.accessToken != rejectedAccessToken &&
        isFresh(current)) {
      _log('using token refreshed by another request');
      return current.accessToken;
    }

    final refreshed = await _refreshSingleFlight();
    if (_explicitSignOutPending) {
      throw const AuthSessionUnavailableException();
    }
    return refreshed.accessToken;
  }

  /// Makes explicit logout authoritative even when a refresh is already in
  /// flight. New requests cannot start or consume refresh while this runs.
  Future<void> signOutExplicitly() async {
    _explicitSignOutPending = true;
    final refresh = _refreshInFlight;
    if (refresh != null) {
      try {
        await refresh;
      } catch (_) {
        // Logout remains authoritative regardless of refresh outcome.
      }
    }

    try {
      await _gateway.signOut();
    } catch (_) {
      _log('explicit sign-out reported an SDK error');
    } finally {
      _explicitSignOutPending = false;
      _explicitlySignedOut = true;
      _log('explicit sign-out completed');
    }
  }

  Future<AuthSessionSnapshot> _refreshSingleFlight() {
    if (_explicitSignOutPending || _explicitlySignedOut) {
      return Future<AuthSessionSnapshot>.error(
        const AuthSessionUnavailableException(),
      );
    }
    final existing = _refreshInFlight;
    if (existing != null) {
      _log('refresh joined/shared');
      return existing;
    }

    _log('refresh started');
    final refresh = _performRefresh();
    _refreshInFlight = refresh;
    refresh.then<void>(
      (_) => _clearRefresh(refresh),
      onError: (_) => _clearRefresh(refresh),
    );
    return refresh;
  }

  void _clearRefresh(Future<AuthSessionSnapshot> refresh) {
    if (identical(_refreshInFlight, refresh)) {
      _refreshInFlight = null;
    }
  }

  Future<AuthSessionSnapshot> _performRefresh() async {
    try {
      final refreshed = await _gateway.refreshSession();
      _log('refresh succeeded');
      return refreshed;
    } on AuthRetryableFetchException catch (error) {
      _log('transient refresh failure; session preserved');
      throw TransientSessionRefreshException(error);
    } on AuthException catch (error) {
      _log('terminal refresh failure; session removed');
      try {
        await _gateway.signOut();
      } catch (_) {
        // GoTrue already removes the local session for terminal refresh errors.
      }
      throw TerminalSessionRefreshException(error);
    } catch (error) {
      // Unknown transport/runtime failures are not authority to erase a session.
      _log('transient refresh failure; session preserved');
      throw TransientSessionRefreshException(error);
    }
  }

  void _log(String message) {
    if (kDebugMode) debugPrint('[SESSION] $message');
  }
}

final authSessionGatewayProvider = Provider<AuthSessionGateway>((ref) {
  return SupabaseAuthSessionGateway(Supabase.instance.client);
});

final authSessionCoordinatorProvider = Provider<AuthSessionCoordinator>((ref) {
  return AuthSessionCoordinator(gateway: ref.watch(authSessionGatewayProvider));
});
