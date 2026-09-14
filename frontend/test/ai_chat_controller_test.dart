import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'package:mediq_app/src/features/auth/data/user_model.dart';
import 'package:mediq_app/src/features/auth/presentation/user_controller.dart';
import 'package:mediq_app/src/features/chat/data/ai_pdf_attachment.dart';
import 'package:mediq_app/src/features/chat/presentation/ai_chat_controller.dart';

class _SwitchingAdapter implements HttpClientAdapter {
  bool fail = false;
  bool staleSave = false;
  final requests = <RequestOptions>[];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<List<int>>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    requests.add(options);
    if (staleSave &&
        options.method == 'POST' &&
        options.path == '/api/v1/vault/ai-summary/save') {
      return ResponseBody.fromString(
        jsonEncode({
          'detail':
              'This saved conversation was updated elsewhere. Your current chat is still available; refresh it before saving.'
        }),
        409,
        headers: {
          Headers.contentTypeHeader: ['application/json'],
        },
      );
    }
    if (fail) {
      throw DioException(
        requestOptions: options,
        type: DioExceptionType.connectionError,
        message: 'test failure',
      );
    }
    return ResponseBody.fromString(
      jsonEncode({'response': 'Please monitor the symptom.'}),
      200,
      headers: {
        Headers.contentTypeHeader: ['application/json'],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

void main() {
  test('profile restoration does not recreate an active AI session', () async {
    final dio = Dio(BaseOptions(baseUrl: 'https://local.test'));
    final container = ProviderContainer(
      overrides: [
        dioProvider.overrideWithValue(dio),
        userProvider.overrideWith((ref) async => User(
              id: '7',
              email: 'patient@example.test',
              firstName: 'Test',
              lastName: 'Patient',
              role: 'patient',
              subscriptionTier: 'premium',
            )),
      ],
    );
    addTearDown(container.dispose);
    await container.read(userProvider.future);
    final subscription = container.listen(
      aiChatControllerProvider(null),
      (_, __) {},
      fireImmediately: true,
    );
    addTearDown(subscription.close);
    final before = container.read(aiChatControllerProvider(null).notifier);

    container.invalidate(userProvider);
    await container.read(userProvider.future);
    await Future<void>.delayed(Duration.zero);

    final after = container.read(aiChatControllerProvider(null).notifier);
    expect(identical(after, before), isTrue);
    expect(after.hasPaidContinuity, isTrue);
  });

  test('new chat without save makes no Vault mutation', () async {
    final adapter = _SwitchingAdapter();
    final dio = Dio(BaseOptions(baseUrl: 'https://local.test'))
      ..httpClientAdapter = adapter;
    final controller = AiChatController(dio, 'free', null);

    await controller.sendMessage('I have a headache');

    expect(controller.state.messages, hasLength(2));
    expect(
      adapter.requests
          .where((request) => request.path.startsWith('/api/v1/vault/')),
      isEmpty,
    );
  });

  test('failed summary save preserves the active conversation for retry',
      () async {
    final adapter = _SwitchingAdapter();
    final dio = Dio(BaseOptions(baseUrl: 'https://local.test'))
      ..httpClientAdapter = adapter;
    final controller = AiChatController(dio, 'premium', null);

    await controller.sendMessage('I have a headache');
    final messagesBeforeSave = controller.state.messages;
    adapter.fail = true;

    expect(await controller.saveSummary(), isFalse);
    expect(controller.state.messages, equals(messagesBeforeSave));
    expect(controller.state.isLoading, isFalse);
    final saveRequest = adapter.requests.last;
    expect(saveRequest.path, '/api/v1/vault/ai-summary/save');
    expect(saveRequest.data.containsKey('summary_text'), isFalse);
  });

  test('continued save updates the same Vault summary instead of creating one',
      () async {
    final adapter = _SwitchingAdapter();
    final dio = Dio(BaseOptions(baseUrl: 'https://local.test'))
      ..httpClientAdapter = adapter;
    const sourceId = '0fd4cda4-bf4c-4cd5-8468-8148de5e4f32';
    const sourceUpdatedAt = '2026-09-04T10:30:00.000Z';
    final controller = AiChatController(
      dio,
      'premium',
      const AiChatContinuation(
        summaryId: sourceId,
        sourceUpdatedAt: sourceUpdatedAt,
      ),
    );

    await controller.sendMessage('The pain is better today');
    expect(await controller.saveSummary(), isTrue);

    final analyzeRequests = adapter.requests
        .where((request) => request.path == '/api/v1/chat/analyze')
        .toList();
    expect(analyzeRequests, hasLength(1));
    for (final request in analyzeRequests) {
      expect(request.data['source_summary_id'], sourceId);
      expect(request.data['source_summary_updated_at'], sourceUpdatedAt);
    }
    final vaultRequests = adapter.requests
        .where((request) => request.path == '/api/v1/vault/ai-summary/save')
        .toList();
    expect(vaultRequests, hasLength(1));
    expect(vaultRequests.single.method, 'POST');
    expect(vaultRequests.single.data['source_updated_at'], sourceUpdatedAt);
    expect(vaultRequests.single.data['source_summary_id'], sourceId);
    expect(vaultRequests.single.data.containsKey('summary_text'), isFalse);
    expect(vaultRequests.single.data['turns'], [
      {'role': 'user', 'text': 'The pain is better today'},
      {'role': 'assistant', 'text': 'Please monitor the symptom.'},
    ]);
  });

  test('stale continuation conflict retains the current chat', () async {
    final adapter = _SwitchingAdapter();
    final dio = Dio(BaseOptions(baseUrl: 'https://local.test'))
      ..httpClientAdapter = adapter;
    final controller = AiChatController(
      dio,
      'premium',
      const AiChatContinuation(
        summaryId: '0fd4cda4-bf4c-4cd5-8468-8148de5e4f32',
        sourceUpdatedAt: '2026-09-04T10:30:00.000Z',
      ),
    );

    await controller.sendMessage('The pain is now mild');
    final messagesBeforeSave = controller.state.messages;
    adapter.staleSave = true;

    expect(await controller.saveSummary(), isFalse);
    expect(controller.state.messages, equals(messagesBeforeSave));
    expect(controller.state.isLoading, isFalse);
  });

  test('summary save sends every turn older than the ten-message window',
      () async {
    final adapter = _SwitchingAdapter();
    final dio = Dio(BaseOptions(baseUrl: 'https://local.test'))
      ..httpClientAdapter = adapter;
    final controller = AiChatController(dio, 'premium', null);

    for (var i = 0; i < 7; i++) {
      final marker = i == 0
          ? 'EARLY_CONTEXT blood pressure changed'
          : i == 6
              ? 'LATEST_CONTEXT pain improved'
              : 'middle turn $i';
      await controller.sendMessage(marker);
    }

    expect(await controller.saveSummary(), isTrue);
    final saveRequest = adapter.requests.singleWhere(
        (request) => request.path == '/api/v1/vault/ai-summary/save');
    final turns = saveRequest.data['turns'] as List<dynamic>;
    expect(turns, hasLength(14));
    expect(turns.first['text'], contains('EARLY_CONTEXT'));
    expect(turns[8]['text'], contains('middle turn 4'));
    expect(turns[12]['text'], contains('LATEST_CONTEXT'));
    expect(saveRequest.data.containsKey('summary_text'), isFalse);
  });

  test('summary retry reuses its idempotency request ID', () async {
    final adapter = _SwitchingAdapter();
    final dio = Dio(BaseOptions(baseUrl: 'https://local.test'))
      ..httpClientAdapter = adapter;
    final controller = AiChatController(dio, 'premium', null);

    await controller.sendMessage('I have a headache');
    adapter.fail = true;
    expect(await controller.saveSummary(), isFalse);
    adapter.fail = false;
    expect(await controller.saveSummary(), isTrue);

    final saves = adapter.requests
        .where((request) => request.path == '/api/v1/vault/ai-summary/save')
        .toList();
    expect(saves, hasLength(2));
    expect(
      saves.first.headers['X-AI-Request-ID'],
      saves.last.headers['X-AI-Request-ID'],
    );
  });

  test('new conversation content starts a new save idempotency operation',
      () async {
    final adapter = _SwitchingAdapter();
    final dio = Dio(BaseOptions(baseUrl: 'https://local.test'))
      ..httpClientAdapter = adapter;
    final controller = AiChatController(dio, 'premium', null);

    await controller.sendMessage('First symptom');
    adapter.fail = true;
    expect(await controller.saveSummary(), isFalse);
    final firstSave = adapter.requests.last;

    adapter.fail = false;
    await controller.sendMessage('A new symptom appeared');
    expect(await controller.saveSummary(), isTrue);
    final saves = adapter.requests
        .where((request) => request.path == '/api/v1/vault/ai-summary/save')
        .toList();

    expect(saves, hasLength(2));
    expect(
      saves.last.headers['X-AI-Request-ID'],
      isNot(firstSave.headers['X-AI-Request-ID']),
    );
    expect(saves.last.data['turns'], hasLength(4));
  });

  test('PDF message uses document endpoint and retains no PDF in chat state',
      () async {
    final adapter = _SwitchingAdapter();
    final dio = Dio(BaseOptions(baseUrl: 'https://local.test'))
      ..httpClientAdapter = adapter;
    final controller = AiChatController(dio, 'free', null);
    final document = AiPdfAttachment(
      name: 'report.pdf',
      bytes: Uint8List.fromList([37, 80, 68, 70]),
    );

    await controller.sendMessage('', document: document);

    expect(adapter.requests.single.path, '/api/v1/chat/analyze-document');
    expect(adapter.requests.single.data, isA<FormData>());
    expect(controller.state.messages.first['documentName'], 'report.pdf');
    expect(
        controller.state.messages.first.containsKey('documentBytes'), isFalse);
  });

  test('Free direct summary save performs no API request', () async {
    final adapter = _SwitchingAdapter();
    final dio = Dio(BaseOptions(baseUrl: 'https://local.test'))
      ..httpClientAdapter = adapter;
    final controller = AiChatController(dio, 'free', null);

    await controller.sendMessage('I have a headache');
    final requestCountBeforeSave = adapter.requests.length;

    expect(await controller.saveSummary(), isFalse);
    expect(adapter.requests.length, requestCountBeforeSave);
    expect(
      adapter.requests
          .where((request) => request.path == '/api/v1/vault/ai-summary/save'),
      isEmpty,
    );
  });

  test(
      'Free first message has no history and follow-up is capped at four messages',
      () async {
    final adapter = _SwitchingAdapter();
    final dio = Dio(BaseOptions(baseUrl: 'https://local.test'))
      ..httpClientAdapter = adapter;
    final controller = AiChatController(dio, 'free', null);

    for (var index = 0; index < 4; index++) {
      await controller.sendMessage('free message $index');
    }

    final analyze = adapter.requests
        .where((request) => request.path == '/api/v1/chat/analyze')
        .toList();
    expect(analyze.first.data['history'], isEmpty);
    expect(analyze[1].data['history'], hasLength(2));
    expect(analyze[2].data['history'], hasLength(4));
    expect(analyze[3].data['history'], hasLength(4));
    expect(analyze[3].data['history'].first['parts'], ['free message 1']);
    for (final request in analyze) {
      expect(request.data.containsKey('conversation_memory'), isFalse);
      expect(request.data.containsKey('memory_source'), isFalse);
      expect(request.data.containsKey('update_memory'), isFalse);
    }
  });

  test('Premium and Family retain ten-message current-session context',
      () async {
    for (final tier in ['premium', 'family']) {
      final adapter = _SwitchingAdapter();
      final dio = Dio(BaseOptions(baseUrl: 'https://local.test'))
        ..httpClientAdapter = adapter;
      final controller = AiChatController(dio, tier, null);

      for (var index = 0; index < 7; index++) {
        await controller.sendMessage('$tier message $index');
      }

      final last = adapter.requests
          .where((request) => request.path == '/api/v1/chat/analyze')
          .last;
      expect(last.data['history'], hasLength(10));
      expect(last.data['history'].first['parts'], ['$tier message 1']);
    }
  });

  test(
      'Paid rolling-memory update remains active while Free cannot activate it',
      () async {
    final paidAdapter = _SwitchingAdapter();
    final paidDio = Dio(BaseOptions(baseUrl: 'https://local.test'))
      ..httpClientAdapter = paidAdapter;
    final paid = AiChatController(paidDio, 'premium', null);
    for (var index = 0; index < 8; index++) {
      await paid.sendMessage('paid turn $index');
    }
    final paidLast = paidAdapter.requests
        .where((request) => request.path == '/api/v1/chat/analyze')
        .last;
    expect(paidLast.data['update_memory'], isTrue);
    expect(paidLast.data['memory_source'], contains('paid turn 0'));

    final freeAdapter = _SwitchingAdapter();
    final freeDio = Dio(BaseOptions(baseUrl: 'https://local.test'))
      ..httpClientAdapter = freeAdapter;
    final free = AiChatController(freeDio, 'free', null);
    for (var index = 0; index < 8; index++) {
      await free.sendMessage('free turn $index');
    }
    final freeLast = freeAdapter.requests
        .where((request) => request.path == '/api/v1/chat/analyze')
        .last;
    expect(freeLast.data['history'], hasLength(4));
    expect(freeLast.data.containsKey('conversation_memory'), isFalse);
    expect(freeLast.data.containsKey('update_memory'), isFalse);
    expect(freeLast.data.containsKey('memory_source'), isFalse);
  });

  test('Equivalent first messages do not send plan-specific quality fields',
      () async {
    final payloads = <Map<dynamic, dynamic>>[];
    for (final tier in ['free', 'premium', 'family']) {
      final adapter = _SwitchingAdapter();
      final dio = Dio(BaseOptions(baseUrl: 'https://local.test'))
        ..httpClientAdapter = adapter;
      await AiChatController(dio, tier, null).sendMessage('Same first prompt');
      payloads.add(adapter.requests.single.data as Map<dynamic, dynamic>);
    }

    expect(payloads.map((payload) => payload['message']).toSet(),
        {'Same first prompt'});
    expect(payloads.every((payload) => payload['history'].isEmpty), isTrue);
    expect(payloads.every((payload) => !payload.containsKey('plan')), isTrue);
  });
}
