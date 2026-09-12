import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mediq_app/src/core/api/auth_interceptor.dart';
import 'package:mediq_app/src/features/auth/data/auth_session_coordinator.dart';

class _Gateway implements AuthSessionGateway {
  _Gateway(this.session, this.refreshed);

  AuthSessionSnapshot? session;
  final AuthSessionSnapshot refreshed;
  int refreshCalls = 0;
  int signOutCalls = 0;

  @override
  AuthSessionSnapshot? get currentSession => session;

  @override
  Future<AuthSessionSnapshot> refreshSession() async {
    refreshCalls += 1;
    session = refreshed;
    return refreshed;
  }

  @override
  Future<void> signOut() async {
    signOutCalls += 1;
    session = null;
  }
}

class _QueueAdapter implements HttpClientAdapter {
  _QueueAdapter(this.statuses);

  final List<int> statuses;
  final List<RequestOptions> requests = [];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    requests.add(options);
    final status = statuses[requests.length - 1];
    return ResponseBody.fromString(
      jsonEncode({'request': requests.length}),
      status,
      headers: {
        Headers.contentTypeHeader: ['application/json']
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

AuthSessionSnapshot _snapshot(String token, DateTime expiry) =>
    AuthSessionSnapshot(
      accessToken: token,
      userId: 'account-a',
      expiresAt: expiry,
    );

({Dio dio, _Gateway gateway, _QueueAdapter adapter}) _harness(
  List<int> statuses, {
  bool expired = false,
}) {
  final now = DateTime.utc(2026, 9, 5, 10);
  final gateway = _Gateway(
    _snapshot(
        'old',
        now.add(
            expired ? const Duration(minutes: -1) : const Duration(hours: 1))),
    _snapshot('new', now.add(const Duration(hours: 2))),
  );
  final coordinator = AuthSessionCoordinator(gateway: gateway, now: () => now);
  final dio = Dio(BaseOptions(baseUrl: 'https://example.test'));
  final adapter = _QueueAdapter(statuses);
  dio.httpClientAdapter = adapter;
  dio.interceptors.add(
    AuthenticatedRequestInterceptor(dio: dio, coordinator: coordinator),
  );
  return (dio: dio, gateway: gateway, adapter: adapter);
}

void main() {
  test('valid token is attached without refresh', () async {
    final h = _harness([200]);
    await h.dio.get('/profile');

    expect(h.adapter.requests.single.headers['Authorization'], 'Bearer old');
    expect(h.gateway.refreshCalls, 0);
  });

  test('expired token refreshes before request and attaches new token',
      () async {
    final h = _harness([200], expired: true);
    await h.dio.get('/profile');

    expect(h.adapter.requests.single.headers['Authorization'], 'Bearer new');
    expect(h.gateway.refreshCalls, 1);
  });

  test('GET 401 refreshes and retries once with the new token', () async {
    final h = _harness([401, 200]);
    final response = await h.dio.get('/profile');

    expect(response.statusCode, 200);
    expect(h.adapter.requests, hasLength(2));
    expect(h.adapter.requests.last.headers['Authorization'], 'Bearer new');
    expect(h.gateway.refreshCalls, 1);
    expect(h.gateway.signOutCalls, 0);
  });

  test('second backend 401 cannot loop and preserves Supabase session',
      () async {
    final h = _harness([401, 401]);

    await expectLater(h.dio.get('/profile'), throwsA(isA<DioException>()));
    expect(h.adapter.requests, hasLength(2));
    expect(h.gateway.refreshCalls, 1);
    expect(h.gateway.signOutCalls, 0);
    expect(h.gateway.session, isNotNull);
  });

  test('unsafe POST refreshes but is never replayed', () async {
    final h = _harness([401]);

    await expectLater(h.dio.post('/payment', data: {'amount': 5}),
        throwsA(isA<DioException>()));
    expect(h.adapter.requests, hasLength(1));
    expect(h.gateway.refreshCalls, 1);
    expect(h.gateway.signOutCalls, 0);
  });

  test('multipart mutation is never replayed even with opt-in flag', () async {
    final h = _harness([401]);

    await expectLater(
      h.dio.post(
        '/upload',
        data: FormData.fromMap({'file': 'body'}),
        options: Options(extra: const {authReplaySafeKey: true}),
      ),
      throwsA(isA<DioException>()),
    );
    expect(h.adapter.requests, hasLength(1));
    expect(h.gateway.refreshCalls, 1);
  });

  test('verified idempotent mutation opts into one replay', () async {
    final h = _harness([401, 200]);

    final response = await h.dio.post(
      '/emergency',
      data: {'request_id': 'stable-id'},
      options: Options(extra: const {authReplaySafeKey: true}),
    );
    expect(response.statusCode, 200);
    expect(h.adapter.requests, hasLength(2));
  });

  test('generic 403 neither signs out nor retries', () async {
    final h = _harness([403]);

    await expectLater(h.dio.get('/forbidden'), throwsA(isA<DioException>()));
    expect(h.adapter.requests, hasLength(1));
    expect(h.gateway.refreshCalls, 0);
    expect(h.gateway.signOutCalls, 0);
    expect(h.gateway.session, isNotNull);
  });
}
