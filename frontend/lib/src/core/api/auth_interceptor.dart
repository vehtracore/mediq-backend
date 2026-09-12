import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import '../../features/auth/data/auth_session_coordinator.dart';
import 'api_error_mapper.dart';
import 'app_exception.dart';

const authRecoveryAttemptedKey = 'mdq.auth_recovery_attempted';
const authReplaySafeKey = 'mdq.auth_replay_safe';

class AuthenticatedRequestInterceptor extends Interceptor {
  AuthenticatedRequestInterceptor({
    required Dio dio,
    required AuthSessionCoordinator coordinator,
  })  : _dio = dio,
        _coordinator = coordinator;

  final Dio _dio;
  final AuthSessionCoordinator _coordinator;

  @override
  void onRequest(
      RequestOptions options, RequestInterceptorHandler handler) async {
    try {
      final token = await _coordinator.accessTokenIfAvailable();
      if (token != null && token.isNotEmpty) {
        options.headers['Authorization'] = 'Bearer $token';
      } else {
        options.headers.remove('Authorization');
        _log('request has no Supabase session');
      }
      _log('${options.method} ${options.path}');
      handler.next(options);
    } on TransientSessionRefreshException {
      handler.reject(_sessionFailure(
        options,
        'Your session could not be refreshed while offline. Please try again.',
      ));
    } on TerminalSessionRefreshException {
      handler.reject(_sessionFailure(
        options,
        'Your session has ended. Please sign in again.',
      ));
    } catch (_) {
      handler.reject(_sessionFailure(
        options,
        'We could not verify your session. Please try again.',
      ));
    }
  }

  @override
  void onResponse(Response response, ResponseInterceptorHandler handler) {
    _log('response ${response.statusCode}');
    handler.next(response);
  }

  @override
  void onError(DioException err, ErrorInterceptorHandler handler) async {
    final options = err.requestOptions;
    final isFirstUnauthorized = err.response?.statusCode == 401 &&
        options.extra[authRecoveryAttemptedKey] != true &&
        _coordinator.currentSession != null;

    if (isFirstUnauthorized) {
      options.extra[authRecoveryAttemptedKey] = true;
      try {
        final rejectedToken = _bearerToken(options.headers['Authorization']);
        final refreshedToken =
            await _coordinator.recoverAfterUnauthorized(rejectedToken);

        if (_isReplaySafe(options)) {
          _log('auth retry performed');
          final retryOptions = options.copyWith(
            headers: {
              ...options.headers,
              'Authorization': 'Bearer $refreshedToken',
            },
            extra: {
              ...options.extra,
              authRecoveryAttemptedKey: true,
            },
          );
          try {
            final response = await _dio.fetch<dynamic>(retryOptions);
            handler.resolve(response);
            return;
          } on DioException catch (retryError) {
            handler.next(_mapped(retryError));
            return;
          }
        }

        _log('session refreshed; unsafe mutation was not replayed');
        handler.next(_mapped(
          err,
          overrideMessage:
              'Your session was refreshed. Please retry this action.',
        ));
        return;
      } on TransientSessionRefreshException {
        _log('401 recovery failed transiently; session preserved');
        handler.next(_mapped(
          err,
          overrideMessage:
              'Your session could not be refreshed while offline. Please try again.',
        ));
        return;
      } on TerminalSessionRefreshException {
        handler.next(_mapped(
          err,
          overrideMessage: 'Your session has ended. Please sign in again.',
        ));
        return;
      } on AuthSessionUnavailableException {
        handler.next(_mapped(err));
        return;
      }
    }

    // A generic 401/403 is never authority to clear the Supabase session.
    handler.next(_mapped(err));
  }

  bool _isReplaySafe(RequestOptions options) {
    final method = options.method.toUpperCase();
    if (method == 'GET' || method == 'HEAD' || method == 'OPTIONS') return true;

    // Mutations require an explicit repository-level idempotency assertion.
    // Multipart/stream bodies are never replayed automatically.
    return options.extra[authReplaySafeKey] == true &&
        options.data is! FormData &&
        options.data is! Stream;
  }

  String? _bearerToken(Object? authorization) {
    if (authorization is! String || !authorization.startsWith('Bearer ')) {
      return null;
    }
    final token = authorization.substring('Bearer '.length);
    return token.isEmpty ? null : token;
  }

  DioException _sessionFailure(RequestOptions options, String message) {
    return DioException(
      requestOptions: options,
      type: DioExceptionType.connectionError,
      message: message,
      error: AppException(message),
    );
  }

  DioException _mapped(DioException error, {String? overrideMessage}) {
    final message =
        overrideMessage ?? ApiErrorMapper.getSecureErrorMessage(error);
    return error.copyWith(
      message: message,
      error: AppException(message, originalException: error),
    );
  }

  void _log(String message) {
    if (kDebugMode) debugPrint('[AUTH HTTP] $message');
  }
}
