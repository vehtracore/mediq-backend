import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:mediq_app/src/core/services/notification_service.dart';

class FakeGateway implements NotificationMessagingGateway {
  final foregroundController =
      StreamController<NotificationEnvelope>.broadcast();
  final openedController = StreamController<NotificationEnvelope>.broadcast();
  final refreshController = StreamController<String>.broadcast();
  NotificationPermissionAvailability permission =
      NotificationPermissionAvailability.enabled;
  NotificationEnvelope? initial;
  String? token = 'token-1';
  int configured = 0;
  int deleted = 0;
  bool deleteFails = false;
  final List<String> events;

  FakeGateway(this.events);

  @override
  Stream<NotificationEnvelope> get foregroundMessages =>
      foregroundController.stream;
  @override
  Stream<NotificationEnvelope> get openedMessages => openedController.stream;
  @override
  Stream<String> get tokenRefreshes => refreshController.stream;
  @override
  Future<void> configureForegroundPresentation() async => configured++;
  @override
  Future<void> deleteToken() async {
    deleted++;
    events.add('delete-local-token');
    if (deleteFails) throw StateError('offline');
  }

  @override
  Future<String?> getToken() async => token;
  @override
  Future<NotificationEnvelope?> initialMessage() async => initial;
  @override
  Future<NotificationPermissionAvailability> permissionStatus() async =>
      permission;
  @override
  Future<NotificationPermissionAvailability> requestPermission() async =>
      permission;
}

class FakeStore implements NotificationLocalStore {
  String installation = '11111111-1111-4111-8111-111111111111';
  bool prompted = false;
  String? pending;
  bool deletionPending = false;

  @override
  Future<void> clearPendingToken() async => pending = null;
  @override
  Future<String> installationId() async => installation;
  @override
  Future<String?> pendingToken() async => pending;
  @override
  Future<bool> permissionPrompted() async => prompted;
  @override
  Future<void> setPendingToken(String token) async => pending = token;
  @override
  Future<void> setPermissionPrompted() async => prompted = true;

  @override
  Future<void> setTokenDeletionPending(bool pending) async {
    deletionPending = pending;
  }

  @override
  Future<bool> tokenDeletionPending() async => deletionPending;
}

void main() {
  late FakeGateway gateway;
  late FakeStore store;
  late List<String> events;
  late List<String> registrations;
  late NotificationService service;
  var registrationFailures = 0;
  var unregisterFails = false;

  setUp(() {
    events = [];
    registrations = [];
    gateway = FakeGateway(events);
    store = FakeStore();
    registrationFailures = 0;
    unregisterFails = false;
    service = NotificationService(
      gateway: gateway,
      store: store,
      registerDevice: ({
        required fcmToken,
        required installationId,
        required platform,
      }) async {
        if (registrationFailures > 0) {
          registrationFailures--;
          throw StateError('offline');
        }
        registrations.add('$installationId:$fcmToken:$platform');
      },
      unregisterDevice: ({required installationId}) async {
        events.add('unregister-backend');
        if (unregisterFails) throw StateError('offline');
      },
      onPermissionChanged: (_) {},
    );
  });

  test('initialization is idempotent and maps foreground/opened/cold messages',
      () async {
    gateway.initial = const NotificationEnvelope(
      data: {'type': 'subscription_activated'},
    );
    final foreground = <NotificationEnvelope>[];
    final intents = <Map<String, dynamic>>[];
    await service.initialize(
      onForegroundMessage: foreground.add,
      onIntent: intents.add,
    );
    await service.initialize(
      onForegroundMessage: foreground.add,
      onIntent: intents.add,
    );
    gateway.foregroundController.add(const NotificationEnvelope(
      data: {'type': 'consultation_confirmed'},
      body: 'Visible',
    ));
    gateway.openedController.add(const NotificationEnvelope(
      data: {'type': 'family_joined'},
    ));
    await Future<void>.delayed(Duration.zero);

    expect(gateway.configured, 1);
    expect(foreground.single.body, 'Visible');
    expect(intents.map((value) => value['type']),
        containsAll(['subscription_activated', 'family_joined']));
  });

  test('token refresh replaces registration and offline state retries at start',
      () async {
    await service.initialize(onForegroundMessage: (_) {}, onIntent: (_) {});
    registrationFailures = 1;
    await service.authenticatedSessionStarted(
      accountKey: 'account-a',
      pushEnabled: true,
    );
    expect(store.pending, 'token-1');

    await service.authenticatedSessionStarted(
      accountKey: 'account-a',
      pushEnabled: true,
    );
    expect(store.pending, isNull);
    expect(registrations, hasLength(1));

    gateway.refreshController.add('token-2');
    await Future<void>.delayed(Duration.zero);
    await Future<void>.delayed(Duration.zero);
    expect(registrations.last, contains(':token-2:'));
  });

  test('logout attempts backend unregister before local deletion', () async {
    await service.authenticatedSessionStarted(
      accountKey: 'account-a',
      pushEnabled: true,
    );
    await service.prepareForLogout();
    expect(events, ['unregister-backend', 'delete-local-token']);
  });

  test('offline unregister still deletes local Firebase token', () async {
    unregisterFails = true;
    await service.prepareForLogout();
    expect(gateway.deleted, 1);
    expect(events, ['unregister-backend', 'delete-local-token']);
  });

  test('failed local deletion is retried before the next registration',
      () async {
    gateway.deleteFails = true;
    await service.prepareForLogout();
    expect(store.deletionPending, isTrue);

    gateway.deleteFails = false;
    await service.authenticatedSessionStarted(
      accountKey: 'account-b',
      pushEnabled: true,
    );
    expect(store.deletionPending, isFalse);
    expect(events, [
      'unregister-backend',
      'delete-local-token',
      'delete-local-token',
    ]);
    expect(registrations, hasLength(1));
  });

  test('denied permission leaves registration inactive', () async {
    gateway.permission = NotificationPermissionAvailability.denied;
    await service.authenticatedSessionStarted(
      accountKey: 'account-a',
      pushEnabled: true,
    );
    expect(registrations, isEmpty);
  });
}
