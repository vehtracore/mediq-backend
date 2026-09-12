import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mediq_app/src/features/emergency/data/emergency_api.dart';

class _EmergencyAdapter implements HttpClientAdapter {
  final requests = <RequestOptions>[];
  int searchStatusCode = 200;
  Object searchBody = const {
    'status': 'success',
    'services': [
      {
        'name': 'Test Hospital',
        'phone_number': '01 234 5678',
        'category': 'hospital',
      },
      {
        'name': 'Test Police',
        'phone_number': '112',
        'category': 'police',
      },
    ],
  };

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<List<int>>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    requests.add(options);
    if (options.path.endsWith('/local-services')) {
      return ResponseBody.fromString(
        jsonEncode(searchBody),
        searchStatusCode,
        headers: {
          Headers.contentTypeHeader: ['application/json'],
        },
      );
    }
    return ResponseBody.fromString(
      jsonEncode({'status': 'accepted'}),
      202,
      headers: {
        Headers.contentTypeHeader: ['application/json'],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

void main() {
  Dio authenticatedDio(_EmergencyAdapter adapter) {
    final dio = Dio(BaseOptions(baseUrl: 'https://local.test'))
      ..httpClientAdapter = adapter;
    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          options.headers['Authorization'] = 'Bearer test-session';
          handler.next(options);
        },
      ),
    );
    return dio;
  }

  test('nearby search uses authenticated Dio and 15 second receive budget',
      () async {
    final adapter = _EmergencyAdapter();
    final api = EmergencyApi(authenticatedDio(adapter));

    final result = await api.searchNearby(latitude: 6.5, longitude: 3.3);

    expect(result.status, NearbySearchStatus.success);
    expect(adapter.requests, hasLength(1));
    expect(adapter.requests.single.headers['Authorization'],
        'Bearer test-session');
    expect(adapter.requests.single.receiveTimeout, const Duration(seconds: 15));
  });

  test('category is consumed from the backend response', () async {
    final adapter = _EmergencyAdapter();
    final result = await EmergencyApi(authenticatedDio(adapter))
        .searchNearby(latitude: 6.5, longitude: 3.3);

    expect(
        result.services.map((item) => item.category), ['hospital', 'police']);
  });

  test('missing or expired session response never appears as live success',
      () async {
    final adapter = _EmergencyAdapter()..searchStatusCode = 401;
    final dio = Dio(BaseOptions(baseUrl: 'https://local.test'))
      ..httpClientAdapter = adapter;

    final result =
        await EmergencyApi(dio).searchNearby(latitude: 6.5, longitude: 3.3);

    expect(result.status, NearbySearchStatus.unavailable);
    expect(result.services, isEmpty);
  });

  test('NOK request carries one stable activation request ID', () async {
    final adapter = _EmergencyAdapter();
    final api = EmergencyApi(authenticatedDio(adapter));

    await api.requestNextOfKinAlert(
      latitude: 6.5,
      longitude: 3.3,
      address: 'Test Area',
      requestId: 'same-activation-1234',
    );

    final request = adapter.requests.single;
    expect(request.method, 'POST');
    expect(request.data['request_id'], 'same-activation-1234');
  });

  test('nearby retry performs only another search and never posts an alert',
      () async {
    final adapter = _EmergencyAdapter();
    final api = EmergencyApi(authenticatedDio(adapter));

    await api.searchNearby(latitude: 6.5, longitude: 3.3);
    await api.searchNearby(latitude: 6.5, longitude: 3.3);

    expect(adapter.requests, hasLength(2));
    expect(
        adapter.requests.every((request) => request.method == 'GET'), isTrue);
    expect(
      adapter.requests.where((request) => request.path.endsWith('/trigger')),
      isEmpty,
    );
  });
}
