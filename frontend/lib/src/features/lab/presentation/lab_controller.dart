import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_image_compress/flutter_image_compress.dart';
import '../data/lab_repository.dart';
import '../data/lab_result_model.dart';
import 'package:path_provider/path_provider.dart';

// State class for the controller
class LabState {
  final bool isLoading;
  final LabAnalysisResponse? result;
  final String? errorMessage;
  final File? capturedImage;

  LabState({
    this.isLoading = false,
    this.result,
    this.errorMessage,
    this.capturedImage,
  });

  LabState copyWith({
    bool? isLoading,
    LabAnalysisResponse? result,
    String? errorMessage,
    File? capturedImage,
  }) {
    return LabState(
      isLoading: isLoading ?? this.isLoading,
      result: result ?? this.result,
      errorMessage: errorMessage, // Nullable to clear error
      capturedImage: capturedImage ?? this.capturedImage,
    );
  }
}

class LabController extends StateNotifier<LabState> {
  final LabRepository _repository;

  LabController(this._repository) : super(LabState());

  Future<void> analyzeImage(XFile imageFile) async {
    if (state.isLoading) return;
    state = state.copyWith(isLoading: true, errorMessage: null);

    try {
      // 1. Compress Image
      final File? compressedFile = await _compressImage(File(imageFile.path));

      if (compressedFile == null) {
        throw Exception("Failed to process image");
      }

      state = state.copyWith(capturedImage: compressedFile);

      // 2. Upload & Analyze
      final result = await _repository.uploadLabImage(compressedFile);

      if (result.status == "REJECTED" || result.status == "ERROR") {
        state = state.copyWith(
          isLoading: false,
          errorMessage:
              result.reason ?? "Image analysis failed. Please try again.",
          result: result,
        );
      } else {
        state = state.copyWith(
          isLoading: false,
          result: result,
        );
      }
    } catch (e) {
      debugPrint('[LabController] analyzeImage error: $e');
      state = state.copyWith(
        isLoading: false,
        errorMessage:
            'Image analysis is temporarily unavailable. Please try again.',
      );
    }
  }

  void reset() {
    state = LabState();
  }

  Future<File?> _compressImage(File file) async {
    try {
      final dir = await getTemporaryDirectory();
      final separator = Platform.pathSeparator;
      final targetPath =
          '${dir.path}$separator${DateTime.now().millisecondsSinceEpoch}_compressed.jpg';

      final result = await FlutterImageCompress.compressAndGetFile(
        file.absolute.path,
        targetPath,
        quality: 70, // Reasonable quality for text extraction vs size
        minWidth: 1024,
        minHeight: 1024,
      );

      return result != null ? File(result.path) : null;
    } catch (e) {
      return file; // Fallback to original if compression fails
    }
  }
}

final labControllerProvider =
    StateNotifierProvider<LabController, LabState>((ref) {
  return LabController(ref.watch(labRepositoryProvider));
});
