import 'package:dio/dio.dart';

import '../api/app_exception.dart';

class UIErrorFormatter {
  static const _fallback = 'An unexpected error occurred. Please try again.';

  /// Patterns that should never appear in user-facing text.
  static final _technicalNoise = RegExp(
    r'DioException|SocketException|FormatException|HttpException|'
    r'ClientException|TimeoutException|HandshakeException|'
    r'type .* is not a subtype|Null check operator|'
    r'\<html|traceback|sql\b|stack\s*trace',
    caseSensitive: false,
  );

  /// Strips the leading "Exception: " wrapper that Dart adds when you
  /// call `.toString()` on a plain `Exception('...')`.
  static final _exceptionPrefix = RegExp(r'^Exception:\s*');

  static String getMessage(dynamic error) {
    final raw = _extractRawMessage(error);
    return _sanitise(raw);
  }

  static String _extractRawMessage(dynamic error) {
    // 1. Our own clean exception type.
    if (error is AppException) {
      return error.message;
    }

    // 2. DioException whose `error` field was set to an AppException
    //    by the interceptor.
    if (error is DioException) {
      if (error.error is AppException) {
        return (error.error as AppException).message;
      }
      // Interceptor may have rewritten `message` to the clean string.
      if (error.message != null && error.message!.isNotEmpty) {
        return error.message!;
      }
    }

    // 3. Plain `Exception('some text')` — strip the "Exception: " prefix.
    if (error is Exception) {
      return error.toString().replaceFirst(_exceptionPrefix, '');
    }

    if (error is String) {
      return error;
    }

    return _fallback;
  }

  /// Ensure nothing technical leaks to users.
  static String _sanitise(String message) {
    if (message.isEmpty || _technicalNoise.hasMatch(message)) {
      return _fallback;
    }
    // Strip any nested "Exception: " or "DioException [...]: " wrappers that
    // may still be embedded from `throw Exception('...: $e')`.
    String cleaned = message.replaceFirst(_exceptionPrefix, '');
    // If after cleaning it still looks technical, use the fallback.
    if (_technicalNoise.hasMatch(cleaned)) {
      return _fallback;
    }
    return cleaned;
  }
}
