import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

const maxAiPdfBytes = 8 * 1024 * 1024;

class AiPdfAttachment {
  final String name;
  final Uint8List bytes;

  const AiPdfAttachment({required this.name, required this.bytes});
}

class AiPdfSelectionException implements Exception {
  final String message;

  const AiPdfSelectionException(this.message);

  @override
  String toString() => message;
}

class AiPdfPicker {
  Future<AiPdfAttachment?> pick() async {
    final result = await FilePicker.pickFiles(
      type: FileType.custom,
      allowedExtensions: const ['pdf'],
      allowMultiple: false,
      withData: true,
    );
    if (result == null || result.files.isEmpty) return null;

    final file = result.files.single;
    try {
      if (file.size > maxAiPdfBytes) {
        throw const AiPdfSelectionException(
          'PDFs must be 8 MB or smaller.',
        );
      }
      final bytes = file.bytes ??
          (file.path == null ? null : await XFile(file.path!).readAsBytes());
      if (bytes == null || bytes.isEmpty) {
        throw const AiPdfSelectionException(
          'This PDF could not be read. Please choose another file.',
        );
      }
      return AiPdfAttachment(
        name: file.name,
        bytes: Uint8List.fromList(bytes),
      );
    } finally {
      try {
        await FilePicker.clearTemporaryFiles();
      } catch (_) {
        // Some desktop/web implementations do not create or expose temp files.
      }
    }
  }
}

final aiPdfPickerProvider = Provider<AiPdfPicker>((ref) => AiPdfPicker());
