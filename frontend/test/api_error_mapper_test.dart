import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mediq_app/src/core/api/api_error_mapper.dart';
import 'package:mediq_app/src/core/api/app_exception.dart';
import 'package:mediq_app/src/core/utils/ui_error_formatter.dart';

DioException _failure({
  required DioExceptionType type,
  int? status,
  dynamic data,
  Map<String, List<String>> headers = const {},
  Object? error,
}) {
  final request = RequestOptions(path: '/test');
  return DioException(
    requestOptions: request,
    type: type,
    error: error,
    response: status == null
        ? null
        : Response<dynamic>(
            requestOptions: request,
            statusCode: status,
            data: data,
            headers: Headers.fromMap(headers),
          ),
  );
}

Map<String, dynamic> _envelope(
  String code,
  String message, {
  dynamic details,
}) =>
    {
      'error': {
        'code': code,
        'message': message,
        'request_id': 'request-1234',
        if (details != null) 'details': details,
      }
    };

void main() {
  test('connection and DNS failures map to offline', () {
    final direct = ApiErrorMapper.map(
      _failure(type: DioExceptionType.connectionError),
    );
    final dns = ApiErrorMapper.map(
      _failure(
        type: DioExceptionType.unknown,
        error: const SocketException('lookup failed'),
      ),
    );

    expect(direct.kind, ApiFailureKind.offline);
    expect(dns.kind, ApiFailureKind.offline);
    expect(direct.retryable, isTrue);
  });

  test('timeouts are distinct from offline failures', () {
    final failure = ApiErrorMapper.map(
      _failure(type: DioExceptionType.receiveTimeout),
    );

    expect(failure.kind, ApiFailureKind.timeout);
    expect(failure.message, contains('longer than expected'));
  });

  test('500 and 503 use distinct safe server messages', () {
    final internal = ApiErrorMapper.map(_failure(
      type: DioExceptionType.badResponse,
      status: 500,
      data: _envelope('internal_error', 'sqlalchemy IntegrityError'),
    ));
    final unavailable = ApiErrorMapper.map(_failure(
      type: DioExceptionType.badResponse,
      status: 503,
      data: _envelope('analysis_unavailable', 'Gemini v1beta failed'),
    ));

    expect(internal.kind, ApiFailureKind.unexpected);
    expect(internal.message, isNot(contains('sqlalchemy')));
    expect(unavailable.kind, ApiFailureKind.serverUnavailable);
    expect(unavailable.message, contains('temporarily unavailable'));
    expect(unavailable.message, isNot(contains('Gemini')));
  });

  test('401 and 403 are classified without session side effects', () {
    final unauthenticated = ApiErrorMapper.map(_failure(
      type: DioExceptionType.badResponse,
      status: 401,
      data: _envelope('unauthenticated', 'Please try again.'),
    ));
    final forbidden = ApiErrorMapper.map(_failure(
      type: DioExceptionType.badResponse,
      status: 403,
      data: _envelope('consultation_not_authorized', 'Access denied.'),
    ));

    expect(unauthenticated.kind, ApiFailureKind.unauthenticated);
    expect(forbidden.kind, ApiFailureKind.forbidden);
  });

  test('409 preserves the backend code', () {
    final failure = ApiErrorMapper.map(_failure(
      type: DioExceptionType.badResponse,
      status: 409,
      data: _envelope('stale_version', 'Refresh and try again.'),
    ));

    expect(failure.kind, ApiFailureKind.conflict);
    expect(failure.code, 'stale_version');
  });

  test('422 preserves safe field validation', () {
    final failure = ApiErrorMapper.map(_failure(
      type: DioExceptionType.badResponse,
      status: 422,
      data: _envelope(
        'validation_error',
        'Check your input.',
        details: {
          'fields': [
            {'field': 'email', 'message': 'Enter a valid email address.'}
          ]
        },
      ),
    ));

    expect(failure.kind, ApiFailureKind.validation);
    expect(failure.fieldErrors['email'], 'Enter a valid email address.');
  });

  test('429 preserves retry-after and domain message', () {
    final failure = ApiErrorMapper.map(_failure(
      type: DioExceptionType.badResponse,
      status: 429,
      data: _envelope(
          'quota_exceeded', 'Your voice allowance resets next month.'),
      headers: {
        'retry-after': ['45']
      },
    ));

    expect(failure.kind, ApiFailureKind.rateLimited);
    expect(failure.code, 'quota_exceeded');
    expect(failure.retryAfter, const Duration(seconds: 45));
    expect(failure.message, contains('allowance'));
  });

  test('cancelled requests do not produce a presentable failure', () {
    final failure = ApiErrorMapper.map(
      _failure(type: DioExceptionType.cancel),
    );

    expect(failure.kind, ApiFailureKind.cancelled);
    expect(failure.shouldPresent, isFalse);
    expect(failure.message, isEmpty);
  });

  test('raw provider and model text never becomes display text', () {
    const raw =
        '404 models/gemini-1.5-flash is not found for API version v1beta generateContent';
    final failure = ApiErrorMapper.map(_failure(
      type: DioExceptionType.badResponse,
      status: 404,
      data: {'detail': raw},
    ));

    expect(failure.message, isNot(contains('gemini')));
    expect(failure.message, isNot(contains('v1beta')));
    expect(failure.message, isNot(contains('generateContent')));
    expect(
        UIErrorFormatter.getMessage(Exception(raw)), isNot(contains('gemini')));
    expect(UIErrorFormatter.getMessage(AppException(raw)),
        isNot(contains('gemini')));
  });

  test('safe domain messages remain available', () {
    final failure = ApiErrorMapper.map(_failure(
      type: DioExceptionType.badResponse,
      status: 400,
      data: _envelope(
        'appointment_not_available',
        'That appointment time is no longer available.',
      ),
    ));

    expect(failure.kind, ApiFailureKind.domain);
    expect(failure.code, 'appointment_not_available');
    expect(failure.message, contains('appointment time'));
    expect(failure.requestId, 'request-1234');
  });
}
