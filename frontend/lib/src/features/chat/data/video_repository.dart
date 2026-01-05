import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';

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
      throw Exception("Failed to join call: $e");
    }
  }
}
