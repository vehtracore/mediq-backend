import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker/image_picker.dart';
import 'package:mediq_app/src/core/api/app_exception.dart';
import 'package:mediq_app/src/features/chat/presentation/ai_chat_controller.dart';
import 'package:mediq_app/src/features/lab/data/lab_repository.dart';
import 'package:mediq_app/src/features/lab/data/lab_result_model.dart';
import 'package:mediq_app/src/features/lab/presentation/lab_controller.dart';

const _rawProviderFailure =
    '404 models/gemini-1.5-flash is not found for API version v1beta generateContent';

class _ProviderFailureAdapter implements HttpClientAdapter {
  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<List<int>>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    return ResponseBody.fromString(
      jsonEncode({'detail': _rawProviderFailure}),
      503,
      headers: {
        Headers.contentTypeHeader: ['application/json'],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

class _RetryingLabRepository extends LabRepository {
  _RetryingLabRepository() : super(Dio());

  int calls = 0;

  @override
  Future<LabAnalysisResponse> uploadLabImage(File imageFile) async {
    calls += 1;
    if (calls == 1) throw AppException(_rawProviderFailure);
    return LabAnalysisResponse(status: 'SUCCESS', lightingScore: 'Good');
  }
}

void main() {
  test('AI chat provider failure never displays provider implementation text',
      () async {
    final dio = Dio(BaseOptions(baseUrl: 'https://local.test'))
      ..httpClientAdapter = _ProviderFailureAdapter();
    final controller = AiChatController(dio, 'premium', null);

    await controller.sendMessage('Help me understand this symptom');

    final message = controller.state.messages.last['message'] as String;
    expect(message, contains('temporarily unavailable'));
    expect(message.toLowerCase(), isNot(contains('gemini')));
    expect(message.toLowerCase(), isNot(contains('v1beta')));
    expect(message.toLowerCase(), isNot(contains('generatecontent')));
  });

  test('scanner failure is safe and a new explicit retry can succeed',
      () async {
    final directory = await Directory.systemTemp.createTemp('mdq_lab_error_');
    addTearDown(() => directory.delete(recursive: true));
    final image = File('${directory.path}${Platform.pathSeparator}strip.jpg');
    await image.writeAsBytes([1, 2, 3]);
    final repository = _RetryingLabRepository();
    final controller = LabController(
      repository,
      compressImage: (file) async => file,
    );

    await controller.analyzeImage(XFile(image.path));

    expect(controller.state.errorMessage, contains('temporarily unavailable'));
    expect(controller.state.errorMessage!.toLowerCase(),
        isNot(contains('gemini')));
    expect(controller.state.isLoading, isFalse);

    await controller.analyzeImage(XFile(image.path));

    expect(repository.calls, 2);
    expect(controller.state.errorMessage, isNull);
    expect(controller.state.result?.status, 'SUCCESS');
  });
}
