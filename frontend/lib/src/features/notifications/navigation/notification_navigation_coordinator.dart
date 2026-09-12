import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'notification_intent.dart';

final notificationNavigationCoordinatorProvider = Provider(
  (_) => NotificationNavigationCoordinator(),
);

class NotificationNavigationCoordinator {
  void Function(String route)? _navigate;
  NotificationIntent? _pending;
  bool _sessionReady = false;

  NotificationIntent? get pendingIntent => _pending;

  void attachNavigator(void Function(String route) navigate) {
    _navigate = navigate;
    _drain();
  }

  void updateSessionReady(bool ready) {
    _sessionReady = ready;
    _drain();
  }

  bool submit(Map<String, dynamic> data) {
    final intent = NotificationIntent.fromData(data);
    if (intent == null) return false;
    _pending = intent;
    _drain();
    return true;
  }

  void clear() {
    _pending = null;
    _sessionReady = false;
  }

  void _drain() {
    final intent = _pending;
    final navigate = _navigate;
    if (!_sessionReady || intent == null || navigate == null) return;
    _pending = null;
    navigate(intent.route);
  }
}
