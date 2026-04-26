import 'package:dio/dio.dart';
import 'package:image_picker/image_picker.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
// For Uint8List

final imageUploadServiceProvider = Provider((ref) => ImageUploadService(ref));

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
      print("Upload Error: $e");
      return null;
    }
  }
}