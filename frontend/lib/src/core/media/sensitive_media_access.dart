import 'package:dio/dio.dart';

class SensitiveMediaAccess {
  final String url;
  final DateTime expiresAt;
  final int expiresIn;
  final String format;

  const SensitiveMediaAccess({
    required this.url,
    required this.expiresAt,
    required this.expiresIn,
    required this.format,
  });

  factory SensitiveMediaAccess.fromJson(Map<String, dynamic> json) {
    return SensitiveMediaAccess(
      url: json['url'] as String,
      expiresAt: DateTime.parse(json['expires_at'] as String),
      expiresIn: json['expires_in'] as int,
      format: json['format'] as String,
    );
  }
}

class SensitiveMediaAccessClient {
  final Dio _dio;

  const SensitiveMediaAccessClient(this._dio);

  Future<SensitiveMediaAccess> doctorDocument({
    required int doctorId,
    required String documentKind,
  }) async {
    final response = await _dio.get(
      '/api/v1/media/doctor-documents/$doctorId/$documentKind/access',
    );
    return SensitiveMediaAccess.fromJson(
      Map<String, dynamic>.from(response.data as Map),
    );
  }

  Future<SensitiveMediaAccess> labImage(int recordId) async {
    final response = await _dio.get(
      '/api/v1/media/lab-images/$recordId/access',
    );
    return SensitiveMediaAccess.fromJson(
      Map<String, dynamic>.from(response.data as Map),
    );
  }
}
