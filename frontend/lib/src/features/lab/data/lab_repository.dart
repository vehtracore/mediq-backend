import 'dart:io';
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'package:mediq_app/src/core/api/app_exception.dart';
import 'package:mediq_app/src/core/utils/ui_error_formatter.dart';
import 'lab_result_model.dart';
import 'package:http_parser/http_parser.dart';

final labRepositoryProvider =
    Provider((ref) => LabRepository(ref.read(dioProvider)));

class LabRepository {
  final Dio _dioClient;

  LabRepository(this._dioClient);

  Future<LabAnalysisResponse> uploadLabImage(File imageFile) async {
    try {
      String fileName = imageFile.path.split('/').last;

      // Basic extension check for MediaType
      String ext = fileName.split('.').last.toLowerCase();
      if (ext == 'jpg') ext = 'jpeg';

      FormData formData = FormData.fromMap({
        'file': await MultipartFile.fromFile(
          imageFile.path,
          filename: fileName,
          contentType: MediaType('image', ext),
        ),
      });

      final response = await _dioClient.post(
        '/api/v1/lab/analyze',
        data: formData,
        options: Options(
          headers: {
            'X-AI-Request-ID': 'lab-${DateTime.now().microsecondsSinceEpoch}',
          },
        ),
      );

      return LabAnalysisResponse.fromJson(response.data);
    } catch (e) {
      throw AppException(
        UIErrorFormatter.getMessage(e),
        originalException: e,
      );
    }
  }
}
