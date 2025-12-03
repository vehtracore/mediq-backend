import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';

final chatRepositoryProvider = Provider<ChatRepository>((ref) {
  return ChatRepository(ref.watch(dioProvider));
});

class ChatRepository {
  final Dio _dio;

  ChatRepository(this._dio);

  Future<String> sendMessage(String message) async {
    try {
      final response = await _dio.post(
        '/api/v1/chat/analyze',
        data: {'message': message},
      );
      // Parse response based on backend schema: {"response": "AI text"}
      return response.data['response'];
    } on DioException catch (e) {
      if (e.response != null && e.response?.data != null) {
        final data = e.response?.data;
        if (data is Map && data.containsKey('detail')) {
          throw Exception(data['detail']);
        }
      }
      throw Exception("Failed to connect to Health Assistant.");
    } catch (e) {
      throw Exception("System error: $e");
    }
  }
}
