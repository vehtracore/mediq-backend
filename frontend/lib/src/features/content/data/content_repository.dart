import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../core/api/dio_client.dart';

// --- Data Model ---
class HealthTip {
  final int id;
  final String title;
  final String category;
  final String readTime;
  final String? imageUrl;
  final String content;

  HealthTip({
    required this.id,
    required this.title,
    required this.category,
    required this.readTime,
    this.imageUrl,
    required this.content,
  });

  factory HealthTip.fromJson(Map<String, dynamic> json) {
    return HealthTip(
      id: json['id'],
      title: json['title'],
      category: json['category'],
      readTime: json['read_time'],
      imageUrl: json['image_url'],
      content: json['content'],
    );
  }
}

// --- Provider ---
final contentRepositoryProvider = Provider<ContentRepository>((ref) {
  return ContentRepository(ref.watch(dioProvider));
});

// --- Repository Class ---
class ContentRepository {
  final Dio _dio;
  ContentRepository(this._dio);

  Future<List<HealthTip>> getHealthTips() async {
    try {
      final response = await _dio.get('/api/v1/content/tips');
      final List data = response.data;
      return data.map((json) => HealthTip.fromJson(json)).toList();
    } catch (e) {
      throw Exception('Failed to load content');
    }
  }

  Future<void> createHealthTip({
    required String title,
    required String category,
    required String readTime,
    required String content,
    String? imageUrl,
  }) async {
    try {
      await _dio.post(
        '/api/v1/content/admin/tips',
        data: {
          "title": title,
          "category": category,
          "read_time": readTime,
          "content": content,
          "image_url": imageUrl,
        },
      );
    } catch (e) {
      throw Exception('Failed to create tip');
    }
  }

  Future<void> updateHealthTip({
    required int id,
    String? title,
    String? category,
    String? readTime,
    String? content,
    String? imageUrl,
  }) async {
    try {
      await _dio.put(
        '/api/v1/content/admin/tips/$id',
        data: {
          if (title != null) "title": title,
          if (category != null) "category": category,
          if (readTime != null) "read_time": readTime,
          if (content != null) "content": content,
          if (imageUrl != null) "image_url": imageUrl,
        },
      );
    } catch (e) {
      throw Exception('Failed to update tip');
    }
  }

  Future<void> deleteHealthTip(int id) async {
    try {
      await _dio.delete('/api/v1/content/admin/tips/$id');
    } catch (e) {
      throw Exception('Failed to delete tip');
    }
  }
}
