import 'dart:io';
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/core/api/api_constants.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'lab_result_model.dart';
import 'package:http_parser/http_parser.dart';

final labRepositoryProvider = Provider((ref) => LabRepository(ref.read(dioProvider)));

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
      );

      return LabAnalysisResponse.fromJson(response.data);
    } catch (e) {
      if (e is DioException && e.response != null) {
        throw Exception(e.response?.data['detail'] ?? 'Upload failed');
      }
      throw Exception('Network error: $e');
    }
  }
}
