import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:image_picker/image_picker.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
// For Uint8List

final imageUploadServiceProvider = Provider((ref) => ImageUploadService(ref));

class TemporaryAiImage {
  final String url;
  final String publicId;

  const TemporaryAiImage({required this.url, required this.publicId});
}

class ImageUploadService {
  final Ref _ref;
  final ImagePicker _picker = ImagePicker();

  ImageUploadService(this._ref);

  // Method 1: Pick AND Upload (Used by Chat)
  Future<String?> pickAndUploadImage() async {
    final XFile? image = await _picker.pickImage(
      source: ImageSource.gallery,
      imageQuality: 90,
      maxWidth: 1920,
      maxHeight: 1920,
    );
    if (image == null) return null;
    return await uploadFile(image);
  }

  Future<TemporaryAiImage?> pickAndUploadTemporaryAiImage() async {
    final XFile? image = await _picker.pickImage(
      source: ImageSource.gallery,
      imageQuality: 90,
      maxWidth: 1920,
      maxHeight: 1920,
    );
    if (image == null) return null;

    try {
      final bytes = await image.readAsBytes();
      final formData = FormData.fromMap({
        'file': MultipartFile.fromBytes(bytes, filename: image.name),
      });
      final response = await _ref
          .read(dioProvider)
          .post('/api/v1/chat/image', data: formData);

      return TemporaryAiImage(
        url: response.data['url'] as String,
        publicId: response.data['public_id'] as String,
      );
    } catch (e) {
      debugPrint('Temporary AI image upload error: $e');
      return null;
    }
  }

  // Method 2: Upload Existing File (Used by Profile Update)
  // ✅ This was missing!
  Future<String?> uploadFile(XFile image) async {
    try {
      final bytes = await image.readAsBytes();
      final fileName = image.name;

      FormData formData = FormData.fromMap({
        "file": MultipartFile.fromBytes(bytes, filename: fileName),
      });

      final dio = _ref.read(dioProvider);
      final response = await dio.post('/api/v1/upload/', data: formData);

      return response.data['url'];
    } catch (e) {
      debugPrint("Upload Error: $e");
      return null;
    }
  }
}
