import 'package:dio/dio.dart';
import 'package:image_picker/image_picker.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
// NOTE: We removed 'dart:io' because it causes issues on Web!

final imageUploadServiceProvider = Provider((ref) => ImageUploadService(ref));

class ImageUploadService {
  final Ref _ref;
  final ImagePicker _picker = ImagePicker();

  ImageUploadService(this._ref);

  Future<String?> pickAndUploadImage() async {
    try {
      // 1. Pick Image (Works on Web & Mobile)
      final XFile? image = await _picker.pickImage(
        source: ImageSource.gallery,
        imageQuality: 70, 
      );

      if (image == null) return null; // User cancelled

      // 2. Prepare Upload (Universal Method: Bytes)
      // On Web, we can't use 'image.path', so we read the bytes directly.
      final bytes = await image.readAsBytes();
      final fileName = image.name;

      FormData formData = FormData.fromMap({
        "file": MultipartFile.fromBytes(
          bytes, 
          filename: fileName
        ),
      });

      // 3. Send to Backend
      final dio = _ref.read(dioProvider);
      final response = await dio.post('/api/v1/upload/', data: formData);

      // 4. Return the URL
      return response.data['url'];
    } catch (e) {
      print("Upload Error: $e");
      return null;
    }
  }
}