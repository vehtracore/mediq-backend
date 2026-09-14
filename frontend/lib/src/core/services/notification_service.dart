import 'dart:async';

import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';

import '../../features/auth/data/auth_repository.dart';

enum NotificationPermissionAvailability {
  unknown,
  notDetermined,
  enabled,
  denied,
}

final notificationPermissionProvider =
    StateProvider<NotificationPermissionAvailability>(
  (_) => NotificationPermissionAvailability.unknown,
);

final notificationServiceProvider = Provider<NotificationService>((ref) {
  final repository = ref.watch(authRepositoryProvider);
  return NotificationService(
    gateway: FirebaseNotificationGateway(),
    store: SharedPreferencesNotificationStore(),
    registerDevice: repository.registerDeviceToken,
    unregisterDevice: repository.unregisterDeviceToken,
    onPermissionChanged: (state) {
      ref.read(notificationPermissionProvider.notifier).state = state;
    },
  );
});

class NotificationEnvelope {
  const NotificationEnvelope({
    required this.data,
    this.title,
    this.body,
  });

  final Map<String, dynamic> data;
  final String? title;
  final String? body;
}

abstract class NotificationMessagingGateway {
  Stream<NotificationEnvelope> get foregroundMessages;
  Stream<NotificationEnvelope> get openedMessages;
  Stream<String> get tokenRefreshes;
  Future<NotificationEnvelope?> initialMessage();
  Future<void> configureForegroundPresentation();
  Future<NotificationPermissionAvailability> permissionStatus();
  Future<NotificationPermissionAvailability> requestPermission();
  Future<String?> getToken();
  Future<void> deleteToken();
}

class FirebaseNotificationGateway implements NotificationMessagingGateway {
  FirebaseNotificationGateway({FirebaseMessaging? messaging})
      : _messaging = messaging ?? FirebaseMessaging.instance;

  final FirebaseMessaging _messaging;

  NotificationEnvelope _envelope(RemoteMessage message) => NotificationEnvelope(
        data: Map<String, dynamic>.from(message.data),
        title: message.notification?.title,
        body: message.notification?.body,
      );

  NotificationPermissionAvailability _permission(AuthorizationStatus status) {
    switch (status) {
      case AuthorizationStatus.authorized:
      case AuthorizationStatus.provisional:
        return NotificationPermissionAvailability.enabled;
      case AuthorizationStatus.denied:
        return NotificationPermissionAvailability.denied;
      case AuthorizationStatus.notDetermined:
        return NotificationPermissionAvailability.notDetermined;
    }
  }

  @override
  Stream<NotificationEnvelope> get foregroundMessages =>
      FirebaseMessaging.onMessage.map(_envelope);

  @override
  Stream<NotificationEnvelope> get openedMessages =>
      FirebaseMessaging.onMessageOpenedApp.map(_envelope);

  @override
  Stream<String> get tokenRefreshes => _messaging.onTokenRefresh;

  @override
  Future<NotificationEnvelope?> initialMessage() async {
    final message = await _messaging.getInitialMessage();
    return message == null ? null : _envelope(message);
  }

  @override
  Future<void> configureForegroundPresentation() {
    return _messaging.setForegroundNotificationPresentationOptions(
      alert: false,
      badge: false,
      sound: false,
    );
  }

  @override
  Future<NotificationPermissionAvailability> permissionStatus() async {
    return _permission(
        (await _messaging.getNotificationSettings()).authorizationStatus);
  }

  @override
  Future<NotificationPermissionAvailability> requestPermission() async {
    final settings = await _messaging.requestPermission(
      alert: true,
      badge: true,
      sound: true,
      provisional: false,
    );
    return _permission(settings.authorizationStatus);
  }

  @override
  Future<String?> getToken() => _messaging.getToken();

  @override
  Future<void> deleteToken() => _messaging.deleteToken();
}

abstract class NotificationLocalStore {
  Future<String> installationId();
  Future<bool> permissionPrompted();
  Future<void> setPermissionPrompted();
  Future<void> setPendingToken(String token);
  Future<String?> pendingToken();
  Future<void> clearPendingToken();
  Future<bool> tokenDeletionPending();
  Future<void> setTokenDeletionPending(bool pending);
}

class SharedPreferencesNotificationStore implements NotificationLocalStore {
  static const _installationKey = 'notification_installation_id';
  static const _permissionPromptedKey = 'notification_permission_prompted';
  static const _pendingTokenKey = 'notification_pending_token';
  static const _tokenDeletionPendingKey = 'notification_token_delete_pending';

  Future<SharedPreferences> get _preferences => SharedPreferences.getInstance();

  @override
  Future<String> installationId() async {
    final preferences = await _preferences;
    final existing = preferences.getString(_installationKey);
    if (existing != null && existing.isNotEmpty) return existing;
    final created = const Uuid().v4();
    await preferences.setString(_installationKey, created);
    return created;
  }

  @override
  Future<bool> permissionPrompted() async =>
      (await _preferences).getBool(_permissionPromptedKey) ?? false;

  @override
  Future<void> setPermissionPrompted() async {
    await (await _preferences).setBool(_permissionPromptedKey, true);
  }

  @override
  Future<void> setPendingToken(String token) async {
    await (await _preferences).setString(_pendingTokenKey, token);
  }

  @override
  Future<String?> pendingToken() async =>
      (await _preferences).getString(_pendingTokenKey);

  @override
  Future<void> clearPendingToken() async {
    await (await _preferences).remove(_pendingTokenKey);
  }

  @override
  Future<bool> tokenDeletionPending() async =>
      (await _preferences).getBool(_tokenDeletionPendingKey) ?? false;

  @override
  Future<void> setTokenDeletionPending(bool pending) async {
    await (await _preferences).setBool(_tokenDeletionPendingKey, pending);
  }
}

typedef RegisterNotificationDevice = Future<void> Function({
  required String fcmToken,
  required String installationId,
  required String platform,
});
typedef UnregisterNotificationDevice = Future<void> Function({
  required String installationId,
});

class NotificationService {
  NotificationService({
    required NotificationMessagingGateway gateway,
    required NotificationLocalStore store,
    required RegisterNotificationDevice registerDevice,
    required UnregisterNotificationDevice unregisterDevice,
    required ValueChanged<NotificationPermissionAvailability>
        onPermissionChanged,
  })  : _gateway = gateway,
        _store = store,
        _registerDevice = registerDevice,
        _unregisterDevice = unregisterDevice,
        _onPermissionChanged = onPermissionChanged;

  final NotificationMessagingGateway _gateway;
  final NotificationLocalStore _store;
  final RegisterNotificationDevice _registerDevice;
  final UnregisterNotificationDevice _unregisterDevice;
  final ValueChanged<NotificationPermissionAvailability> _onPermissionChanged;

  bool _initialized = false;
  bool _pushEnabled = false;
  String? _accountKey;
  void Function(NotificationEnvelope message)? _onForegroundMessage;
  void Function(Map<String, dynamic> data)? _onIntent;
  final List<StreamSubscription<dynamic>> _subscriptions = [];

  Future<void> initialize({
    required void Function(NotificationEnvelope message) onForegroundMessage,
    required void Function(Map<String, dynamic> data) onIntent,
  }) async {
    _onForegroundMessage = onForegroundMessage;
    _onIntent = onIntent;
    if (_initialized) return;
    _initialized = true;

    try {
      await _gateway.configureForegroundPresentation();
    } catch (_) {}
    try {
      _onPermissionChanged(await _gateway.permissionStatus());
    } catch (_) {
      _onPermissionChanged(NotificationPermissionAvailability.unknown);
    }
    _subscriptions.add(_gateway.foregroundMessages.listen((message) {
      _onForegroundMessage?.call(message);
    }));
    _subscriptions.add(_gateway.openedMessages.listen((message) {
      _onIntent?.call(message.data);
    }));
    _subscriptions.add(_gateway.tokenRefreshes.listen((token) {
      if (_accountKey != null && _pushEnabled) {
        unawaited(_registerToken(token));
      }
    }));

    try {
      final initial = await _gateway.initialMessage();
      if (initial != null) _onIntent?.call(initial.data);
    } catch (_) {}
  }

  Future<NotificationPermissionAvailability> refreshPermissionStatus() async {
    NotificationPermissionAvailability state;
    try {
      state = await _gateway.permissionStatus();
    } catch (_) {
      state = NotificationPermissionAvailability.unknown;
    }
    _onPermissionChanged(state);
    return state;
  }

  Future<NotificationPermissionAvailability> _ensurePermission({
    required bool userInitiated,
  }) async {
    var state = await refreshPermissionStatus();
    if (state != NotificationPermissionAvailability.notDetermined) return state;
    if (!userInitiated && await _store.permissionPrompted()) return state;
    await _store.setPermissionPrompted();
    try {
      state = await _gateway.requestPermission();
    } catch (_) {
      state = NotificationPermissionAvailability.unknown;
    }
    _onPermissionChanged(state);
    return state;
  }

  Future<void> authenticatedSessionStarted({
    required String accountKey,
    required bool pushEnabled,
  }) async {
    if (await _store.tokenDeletionPending()) {
      final deleted = await _deleteTokenForIsolation();
      if (!deleted) return;
    }
    if (_accountKey != null && _accountKey != accountKey) {
      if (!await _deleteTokenForIsolation()) return;
      await _store.clearPendingToken();
    }
    _accountKey = accountKey;
    _pushEnabled = pushEnabled;
    if (!pushEnabled) {
      await refreshPermissionStatus();
      return;
    }
    final permission = await _ensurePermission(userInitiated: false);
    if (permission != NotificationPermissionAvailability.enabled) return;
    final token = await _currentOrPendingToken();
    if (token != null && token.isNotEmpty) await _registerToken(token);
  }

  Future<NotificationPermissionAvailability> enablePush() async {
    _pushEnabled = true;
    final permission = await _ensurePermission(userInitiated: true);
    if (permission == NotificationPermissionAvailability.enabled &&
        _accountKey != null) {
      final token = await _currentOrPendingToken();
      if (token != null && token.isNotEmpty) await _registerToken(token);
    }
    return permission;
  }

  void disablePush() {
    _pushEnabled = false;
  }

  Future<String?> _currentOrPendingToken() async {
    try {
      return await _gateway.getToken() ?? await _store.pendingToken();
    } catch (_) {
      return _store.pendingToken();
    }
  }

  Future<void> _registerToken(String token) async {
    try {
      await _registerDevice(
        fcmToken: token,
        installationId: await _store.installationId(),
        platform: _platform,
      );
      await _store.clearPendingToken();
    } catch (error) {
      await _store.setPendingToken(token);
      if (kDebugMode) {
        debugPrint(
          '[NOTIFICATIONS] registration deferred failure_type=${error.runtimeType}',
        );
      }
    }
  }

  Future<void> prepareForLogout() async {
    try {
      final installationId = await _store.installationId();
      await _unregisterDevice(installationId: installationId);
    } catch (_) {
      // Token deletion below still invalidates offline/stale account delivery.
    }
    await _deleteTokenForIsolation();
    try {
      await _store.clearPendingToken();
    } catch (_) {}
    _accountKey = null;
    _pushEnabled = false;
  }

  Future<void> handleTerminalSignOut() async {
    await _deleteTokenForIsolation();
    try {
      await _store.clearPendingToken();
    } catch (_) {}
    _accountKey = null;
    _pushEnabled = false;
  }

  Future<bool> _deleteTokenForIsolation() async {
    try {
      await _store.setTokenDeletionPending(true);
    } catch (_) {}
    try {
      await _gateway.deleteToken();
      try {
        await _store.setTokenDeletionPending(false);
      } catch (_) {}
      return true;
    } catch (_) {
      return false;
    }
  }

  String get _platform {
    if (kIsWeb) return 'web';
    switch (defaultTargetPlatform) {
      case TargetPlatform.android:
        return 'android';
      case TargetPlatform.iOS:
        return 'ios';
      case TargetPlatform.macOS:
        return 'macos';
      case TargetPlatform.windows:
        return 'windows';
      case TargetPlatform.linux:
        return 'linux';
      case TargetPlatform.fuchsia:
        return 'android';
    }
  }
}
