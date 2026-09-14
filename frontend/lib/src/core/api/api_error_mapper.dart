import 'dart:io';

import 'package:dio/dio.dart';

enum ApiFailureKind {
  offline,
  timeout,
  serverUnavailable,
  unauthenticated,
  forbidden,
  validation,
  conflict,
  rateLimited,
  notFound,
  cancelled,
  domain,
  unexpected,
}

class ApiFailure {
  const ApiFailure({
    required this.kind,
    required this.message,
    this.code,
    this.statusCode,
    this.retryable = false,
    this.retryAfter,
    this.fieldErrors = const {},
    this.requestId,
  });

  final ApiFailureKind kind;
  final String message;
  final String? code;
  final int? statusCode;
  final bool retryable;
  final Duration? retryAfter;
  final Map<String, String> fieldErrors;
  final String? requestId;

  bool get shouldPresent => kind != ApiFailureKind.cancelled;

  ApiFailure copyWith({String? message}) => ApiFailure(
        kind: kind,
        message: message ?? this.message,
        code: code,
        statusCode: statusCode,
        retryable: retryable,
        retryAfter: retryAfter,
        fieldErrors: fieldErrors,
        requestId: requestId,
      );
}

class ApiErrorMapper {
  static const _unexpectedMessage =
      "We couldn't complete that request. Please try again.";
  static const _unavailableMessage =
      'MDQ+ is temporarily unavailable. Please try again shortly.';
  static const _offlineMessage =
      "We couldn't connect. Check your internet connection and try again.";
  static const _timeoutMessage =
      'This is taking longer than expected. Please try again.';

  static final RegExp _unsafeText = RegExp(
    r'<html|traceback|stack\s*trace|sql(?:alchemy)?\b|exception\b|'
    r'dioexception|socketexception|httpexception|formatexception|'
    r'gemini|generatecontent|v1beta|googlegenerativeai|openai|yarngpt|'
    r'paystack|resend|termii|firebase|agora|cloudinary|'
    r'api[_ -]?key|bearer\s+|models/',
    caseSensitive: false,
  );

  static ApiFailure map(dynamic error) {
    if (error is! DioException) {
      return const ApiFailure(
        kind: ApiFailureKind.unexpected,
        message: _unexpectedMessage,
      );
    }

    switch (error.type) {
      case DioExceptionType.cancel:
        return const ApiFailure(kind: ApiFailureKind.cancelled, message: '');
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.sendTimeout:
      case DioExceptionType.receiveTimeout:
        return const ApiFailure(
          kind: ApiFailureKind.timeout,
          message: _timeoutMessage,
          retryable: true,
        );
      case DioExceptionType.connectionError:
        return const ApiFailure(
          kind: ApiFailureKind.offline,
          message: _offlineMessage,
          retryable: true,
        );
      case DioExceptionType.unknown:
        if (error.error is SocketException) {
          return const ApiFailure(
            kind: ApiFailureKind.offline,
            message: _offlineMessage,
            retryable: true,
          );
        }
        return const ApiFailure(
          kind: ApiFailureKind.unexpected,
          message: _unexpectedMessage,
        );
      case DioExceptionType.badCertificate:
        return const ApiFailure(
          kind: ApiFailureKind.unexpected,
          message: _unexpectedMessage,
        );
      case DioExceptionType.badResponse:
        return _fromResponse(error.response);
    }
  }

  static String getSecureErrorMessage(dynamic error) => map(error).message;

  static String safeDisplayMessage(String message) =>
      _safeMessage(message) ?? _unexpectedMessage;

  static ApiFailure _fromResponse(Response<dynamic>? response) {
    final status = response?.statusCode;
    final envelope = _errorEnvelope(response?.data);
    final code = _cleanScalar(envelope?['code']);
    final requestId = _cleanScalar(envelope?['request_id']) ??
        _cleanScalar(response?.headers.value('x-request-id'));
    final backendMessage = _safeMessage(envelope?['message']);
    final retryAfter = _retryAfter(response?.headers.value('retry-after'));
    final fields = _fieldErrors(envelope?['details']);

    switch (status) {
      case 401:
        return ApiFailure(
          kind: ApiFailureKind.unauthenticated,
          message: backendMessage ??
              'We could not authorize this request. Please try again.',
          code: code ?? 'unauthenticated',
          statusCode: status,
          requestId: requestId,
        );
      case 403:
        return ApiFailure(
          kind: ApiFailureKind.forbidden,
          message: backendMessage ??
              'You do not have permission to perform this action.',
          code: code ?? 'forbidden',
          statusCode: status,
          requestId: requestId,
        );
      case 404:
        return ApiFailure(
          kind: ApiFailureKind.notFound,
          message: backendMessage ?? 'The requested item was not found.',
          code: code ?? 'not_found',
          statusCode: status,
          requestId: requestId,
        );
      case 409:
        return ApiFailure(
          kind: ApiFailureKind.conflict,
          message: backendMessage ??
              'This request conflicts with the current state. Please refresh and try again.',
          code: code ?? 'request_conflict',
          statusCode: status,
          requestId: requestId,
        );
      case 422:
        return ApiFailure(
          kind: ApiFailureKind.validation,
          message: backendMessage ?? 'Please check your input and try again.',
          code: code ?? 'validation_error',
          statusCode: status,
          fieldErrors: fields,
          requestId: requestId,
        );
      case 429:
        return ApiFailure(
          kind: ApiFailureKind.rateLimited,
          message:
              backendMessage ?? 'Too many requests. Please wait and try again.',
          code: code ?? 'rate_limited',
          statusCode: status,
          retryable: true,
          retryAfter: retryAfter,
          requestId: requestId,
        );
      case 502:
      case 503:
      case 504:
        return ApiFailure(
          kind: ApiFailureKind.serverUnavailable,
          message: _unavailableMessage,
          code: code ?? 'service_unavailable',
          statusCode: status,
          retryable: true,
          retryAfter: retryAfter,
          requestId: requestId,
        );
      default:
        if (status != null && status >= 500) {
          return ApiFailure(
            kind: ApiFailureKind.unexpected,
            message: _unexpectedMessage,
            code: code ?? 'internal_error',
            statusCode: status,
            retryable: true,
            requestId: requestId,
          );
        }
        return ApiFailure(
          kind: ApiFailureKind.domain,
          message: backendMessage ?? _unexpectedMessage,
          code: code ?? 'request_failed',
          statusCode: status,
          fieldErrors: fields,
          requestId: requestId,
        );
    }
  }

  static Map<dynamic, dynamic>? _errorEnvelope(dynamic data) {
    if (data is! Map) return null;
    final error = data['error'];
    if (error is Map) return error;
    return {
      'code': data['error_code'],
      'message': data['detail'],
      'details': data['details'],
    };
  }

  static String? _safeMessage(dynamic value) {
    final text = _cleanScalar(value);
    if (text == null || text.length > 500 || _unsafeText.hasMatch(text)) {
      return null;
    }
    return text;
  }

  static String? _cleanScalar(dynamic value) {
    if (value is! String) return null;
    final text = value.trim();
    return text.isEmpty ? null : text;
  }

  static Map<String, String> _fieldErrors(dynamic details) {
    if (details is! Map || details['fields'] is! List) return const {};
    final result = <String, String>{};
    for (final item in details['fields'] as List) {
      if (item is! Map) continue;
      final field = _cleanScalar(item['field']);
      final message = _safeMessage(item['message']);
      if (field != null && message != null) result[field] = message;
    }
    return result;
  }

  static Duration? _retryAfter(String? value) {
    if (value == null) return null;
    final seconds = int.tryParse(value.trim());
    if (seconds != null && seconds >= 0) return Duration(seconds: seconds);
    final date = DateTime.tryParse(value)?.toUtc();
    if (date == null) return null;
    final remaining = date.difference(DateTime.now().toUtc());
    return remaining.isNegative ? Duration.zero : remaining;
  }
}
