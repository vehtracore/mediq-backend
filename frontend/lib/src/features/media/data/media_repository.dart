import 'dart:io'; // Keep for Mobile check
import 'package:flutter/foundation.dart' show kIsWeb; // To check if on Web
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http_parser/http_parser.dart';
import 'package:image_picker/image_picker.dart'; // Change input type to XFile
import 'package:mediq_app/src/core/api/dio_client.dart';

final mediaRepositoryProvider = Provider<MediaRepository>((ref) {
  return MediaRepository(ref.watch(dioProvider));
});

class MediaRepository {
  final Dio _dio;

  MediaRepository(this._dio);

  // CHANGED: Input is now XFile (works on Web & Mobile)
  Future<String> uploadFile(
    XFile file, {
    String folder = "mdq_plus/general",
  }) async {
    try {
      FormData formData;

      if (kIsWeb) {
        // 🌐 WEB STRATEGY: Read as Bytes
        // Browsers can't read file paths, so we send the raw bytes directly.
        final bytes = await file.readAsBytes();
        formData = FormData.fromMap({
          "file": MultipartFile.fromBytes(
            bytes,
            filename: file.name,
            contentType: MediaType('image', 'jpeg'),
          ),
          "folder": folder,
        });
      } else {
        // 📱 MOBILE STRATEGY: Read from Path
        // Phones are efficient reading directly from the file system.
        formData = FormData.fromMap({
          "file": await MultipartFile.fromFile(
            file.path,
            filename: file.name,
            contentType: MediaType('image', 'jpeg'),
          ),
          "folder": folder,
        });
      }

      final response = await _dio.post('/api/v1/media/upload', data: formData);

      return response.data['url'];
    } catch (e) {
      throw Exception("Upload failed: $e");
    }
  }
}
