import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';

final reviewRepositoryProvider = Provider<ReviewRepository>((ref) {
  return ReviewRepository(ref.watch(dioProvider));
});

class ReviewRepository {
  final Dio _dio;
  ReviewRepository(this._dio);

  Future<void> submitReview({
    required int appointmentId,
    required int rating,
    String? comment,
  }) async {
    try {
      await _dio.post(
        '/api/v1/reviews/',
        data: {
          "appointment_id": appointmentId,
          "rating": rating,
          "comment": comment,
        },
      );
    } catch (e) {
      throw Exception('Failed to submit review');
    }
  }
}
