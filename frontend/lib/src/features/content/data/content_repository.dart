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
  final String? externalLink;
  final String content;

  HealthTip({
    required this.id,
    required this.title,
    required this.category,
    required this.readTime,
    this.imageUrl,
    this.externalLink,
    required this.content,
  });

  factory HealthTip.fromJson(Map<String, dynamic> json) {
    return HealthTip(
      id: json['id'],
      title: json['title'],
      category: json['category'],
      readTime: json['read_time'],
      imageUrl: _sanitizeHealthTipImageUrl(json['image_url']),
      externalLink: json['external_url'],
      content: json['content'],
    );
  }

  static String? _sanitizeHealthTipImageUrl(dynamic value) {
    if (value is! String) return null;

    final trimmed = value.trim();
    if (trimmed.isEmpty || !trimmed.startsWith('http')) return null;

    final host = Uri.tryParse(trimmed)?.host.toLowerCase() ?? '';
    final isRandomPlaceholderHost =
        host == 'source.unsplash.com' ||
        host == 'images.unsplash.com' ||
        host == 'picsum.photos' ||
        host == 'loremflickr.com' ||
        host == 'placehold.co' ||
        host.contains('placeholder');

    return isRandomPlaceholderHost ? null : trimmed;
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

  String? _normalizeOptionalUrl(String? value) {
    final trimmed = value?.trim();
    if (trimmed == null || trimmed.isEmpty) return null;
    return trimmed;
  }

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
    String? externalLink,
  }) async {
    try {
      await _dio.post(
        '/api/v1/content/admin/tips',
        data: {
          "title": title,
          "category": category,
          "read_time": readTime,
          "content": content,
          "image_url": _normalizeOptionalUrl(imageUrl),
          "external_url": _normalizeOptionalUrl(externalLink),
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
    String? externalLink,
    bool includeImageUrl = false,
  }) async {
    try {
      final normalizedImageUrl = _normalizeOptionalUrl(imageUrl);
      await _dio.put(
        '/api/v1/content/admin/tips/$id',
        data: {
          if (title != null) "title": title,
          if (category != null) "category": category,
          if (readTime != null) "read_time": readTime,
          if (content != null) "content": content,
          if (includeImageUrl) "image_url": normalizedImageUrl,
          if (externalLink != null)
            "external_url": _normalizeOptionalUrl(externalLink),
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
