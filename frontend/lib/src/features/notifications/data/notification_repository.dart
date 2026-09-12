import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/dio_client.dart';
import 'notification_record.dart';

final notificationRepositoryProvider = Provider((ref) {
  return NotificationRepository(ref.watch(dioProvider));
});

final notificationsProvider =
    FutureProvider.autoDispose<List<NotificationRecord>>(
  (ref) => ref.watch(notificationRepositoryProvider).list(),
);

final unreadNotificationCountProvider = FutureProvider<int>(
  (ref) => ref.watch(notificationRepositoryProvider).unreadCount(),
);

class NotificationRepository {
  NotificationRepository(this._dio);

  final Dio _dio;

  Future<List<NotificationRecord>> list() async {
    final response = await _dio.get('/api/v1/notifications/');
    final values = response.data as List<dynamic>;
    return values
        .map((value) => NotificationRecord.fromJson(
              Map<String, dynamic>.from(value as Map),
            ))
        .toList(growable: false);
  }

  Future<int> unreadCount() async {
    final response = await _dio.get('/api/v1/notifications/unread-count');
    return (response.data['unread_count'] as num?)?.toInt() ?? 0;
  }

  Future<void> markRead(int notificationId) async {
    await _dio.patch('/api/v1/notifications/$notificationId/read');
  }

  Future<void> markAllRead() async {
    await _dio.post('/api/v1/notifications/read-all');
  }
}
