import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'package:mediq_app/src/core/api/app_exception.dart';
import 'package:mediq_app/src/core/utils/ui_error_formatter.dart';

final videoRepositoryProvider = Provider(
  (ref) => VideoRepository(ref.watch(dioProvider)),
);

class VideoRepository {
  final Dio _dio;
  VideoRepository(this._dio);

  Future<Map<String, dynamic>> getConnectionData(int appointmentId) async {
    try {
      final response = await _dio.get('/api/v1/video/token/$appointmentId');
      return response.data;
      // Returns: { "token": "...", "channel": "...", "app_id": "...", "uid": 123 }
    } catch (e) {
      throw AppException(
        UIErrorFormatter.getMessage(e),
        originalException: e,
      );
    }
  }
}
