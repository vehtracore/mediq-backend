import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'notification_intent.dart';

final notificationNavigationCoordinatorProvider = Provider(
  (_) => NotificationNavigationCoordinator(),
);

class NotificationNavigationCoordinator {
  void Function(String route)? _navigate;
  Map<String, dynamic>? _pendingData;
  bool _sessionReady = false;
  String? _role;

  NotificationIntent? get pendingIntent => _pendingData == null
      ? null
      : NotificationIntent.fromData(_pendingData!, role: _role);

  void attachNavigator(void Function(String route) navigate) {
    _navigate = navigate;
    _drain();
  }

  void updateSessionReady(bool ready, {String? role}) {
    _sessionReady = ready;
    _role = role;
    _drain();
  }

  bool submit(Map<String, dynamic> data) {
    final intent = NotificationIntent.fromData(data, role: _role);
    if (intent == null) return false;
    _pendingData = data;
    _drain();
    return true;
  }

  void clear() {
    _pendingData = null;
    _sessionReady = false;
    _role = null;
  }

  void _drain() {
    final intent = pendingIntent;
    final navigate = _navigate;
    if (!_sessionReady || intent == null || navigate == null) return;
    _pendingData = null;
    navigate(intent.route);
  }
}
