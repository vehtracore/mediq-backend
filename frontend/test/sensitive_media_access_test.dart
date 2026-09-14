import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mediq_app/src/core/media/sensitive_media_access.dart';

class _SensitiveMediaAdapter implements HttpClientAdapter {
  final requests = <RequestOptions>[];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<List<int>>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    requests.add(options);
    return ResponseBody.fromString(
      jsonEncode({
        'url': 'https://api.cloudinary.test/download?signature=temporary',
        'expires_at': '2026-09-14T12:05:00Z',
        'expires_in': 300,
        'format': options.path.contains('indemnity') ? 'pdf' : 'png',
      }),
      200,
      headers: {
        Headers.contentTypeHeader: ['application/json'],
        'cache-control': ['no-store, private'],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

void main() {
  test('doctor viewer requests a record-bound temporary access URL', () async {
    final dio = Dio(BaseOptions(baseUrl: 'https://local.test'));
    final adapter = _SensitiveMediaAdapter();
    dio.httpClientAdapter = adapter;

    final access = await SensitiveMediaAccessClient(dio).doctorDocument(
      doctorId: 42,
      documentKind: 'indemnity-certificate',
    );

    expect(
      adapter.requests.single.path,
      '/api/v1/media/doctor-documents/42/indemnity-certificate/access',
    );
    expect(access.expiresIn, 300);
    expect(access.format, 'pdf');
    expect(access.url, contains('signature=temporary'));
  });

  test('patient viewer requests access by logical lab record ID', () async {
    final dio = Dio(BaseOptions(baseUrl: 'https://local.test'));
    final adapter = _SensitiveMediaAdapter();
    dio.httpClientAdapter = adapter;

    final access = await SensitiveMediaAccessClient(dio).labImage(88);

    expect(
      adapter.requests.single.path,
      '/api/v1/media/lab-images/88/access',
    );
    expect(access.expiresAt.toUtc(), DateTime.utc(2026, 9, 14, 12, 5));
    expect(access.expiresIn, lessThanOrEqualTo(300));
  });
}
