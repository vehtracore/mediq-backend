import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'package:mediq_app/src/core/api/app_exception.dart';
import 'package:mediq_app/src/core/utils/ui_error_formatter.dart';

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
    } catch (e) {
      throw AppException(
        UIErrorFormatter.getMessage(e),
        originalException: e,
      );
    }
  }

}
