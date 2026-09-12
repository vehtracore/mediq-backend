import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mediq_app/src/features/chat/data/voice_input_capability.dart';
import 'package:mediq_app/src/features/chat/data/voice_input_service.dart';
import 'package:mediq_app/src/features/chat/presentation/voice_input_controller.dart';
import 'package:mediq_app/src/features/chat/presentation/widgets/voice_input_microphone_button.dart';

class _FakePermission implements MicrophonePermissionPort {
  MicrophonePermissionResult result = MicrophonePermissionResult.granted;
  Completer<MicrophonePermissionResult>? pending;
  Object? error;
  int requests = 0;
  int settingsOpened = 0;

  @override
  Future<MicrophonePermissionResult> request() async {
    requests += 1;
    if (error case final error?) throw error;
    if (pending case final pending?) return pending.future;
    return result;
  }

  @override
  Future<bool> openSettings() async {
    settingsOpened += 1;
    return true;
  }
}

class _FakeRecorder implements VoiceRecorderPort {
  final controller = StreamController<VoiceRecorderEvent>.broadcast();
  int starts = 0;
  int stops = 0;
  int cancels = 0;
  String? path;

  @override
  Stream<VoiceRecorderEvent> get events => controller.stream;

  @override
  Future<void> start(String path) async {
    starts += 1;
    this.path = path;
    controller.add(VoiceRecorderEvent.recording);
  }

  @override
  Future<String?> stop() async {
    stops += 1;
    controller.add(VoiceRecorderEvent.stopped);
    return path;
  }

  @override
  Future<void> cancel() async {
    cancels += 1;
  }

  @override
  Future<void> dispose() => controller.close();
}

class _FakeTempFiles implements VoiceTempFilePort {
  int cleanups = 0;
  int sequence = 0;
  final deleted = <String?>[];

  @override
  Future<void> cleanupStale() async {
    cleanups += 1;
  }

  @override
  Future<String> createPath() async => '/tmp/mdq_voice_input_${sequence++}.m4a';

  @override
  Future<void> delete(String? path) async {
    if (path != null) deleted.add(path);
  }
}

class _FakeTranscription implements VoiceTranscriptionPort {
  final List<Object> results;
  int calls = 0;
  int cancels = 0;
  String? language;
  Completer<String>? pending;

  _FakeTranscription([this.results = const ['the transcript']]);

  @override
  Future<String> transcribe({
    required String path,
    required String language,
    required String requestId,
  }) async {
    calls += 1;
    this.language = language;
    if (pending != null) return pending!.future;
    final result = results[(calls - 1).clamp(0, results.length - 1)];
    if (result is Exception) throw result;
    return result as String;
  }

  @override
  Future<void> cancelActive() async {
    cancels += 1;
  }
}

VoiceInputController _controller({
  _FakeRecorder? recorder,
  _FakeTranscription? transcription,
  _FakeTempFiles? tempFiles,
  _FakePermission? permission,
  Duration maximumDuration = const Duration(seconds: 90),
}) {
  return VoiceInputController(
    recorder: recorder ?? _FakeRecorder(),
    transcription: transcription ?? _FakeTranscription(),
    tempFiles: tempFiles ?? _FakeTempFiles(),
    permission: permission ?? _FakePermission(),
    maximumDuration: maximumDuration,
    timerInterval: const Duration(milliseconds: 5),
  );
}

void main() {
  test(
      'central capability map enables only English and Nigerian Pidgin voice input',
      () {
    expect(aiLanguageCapabilities.keys.toSet(), {
      'English',
      'Nigerian Pidgin',
      'Yoruba',
      'Hausa',
      'Igbo',
    });
    for (final entry in aiLanguageCapabilities.entries) {
      expect(entry.value.typedInputEnabled, isTrue, reason: entry.key);
      expect(entry.value.voiceOutputEnabled, isTrue, reason: entry.key);
      expect(
        entry.value.voiceInputEnabled,
        {'English', 'Nigerian Pidgin'}.contains(entry.key),
        reason: entry.key,
      );
    }
  });

  testWidgets(
      'microphone widget is enabled for English and visibly unavailable for Yoruba',
      (tester) async {
    var taps = 0;
    Future<void> pump(String language) => tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: VoiceInputMicrophoneButton(
                selectedLanguage: language,
                phase: VoiceInputPhase.idle,
                interactionEnabled: true,
                onPressed: () => taps += 1,
              ),
            ),
          ),
        );

    await pump('English');
    expect(find.byIcon(Icons.mic_none), findsOneWidget);
    await tester.tap(find.byType(IconButton));
    expect(taps, 1);

    await pump('Yoruba');
    expect(find.byIcon(Icons.mic_off_outlined), findsOneWidget);
    expect(find.bySemanticsLabel('Voice input unavailable for Yoruba'),
        findsOneWidget);
  });

  test('first tap starts once and natural silence does not stop recording',
      () async {
    final recorder = _FakeRecorder();
    final controller = _controller(recorder: recorder);
    addTearDown(controller.disposeAsync);

    expect(
      await controller.start(language: 'English', existingComposerText: ''),
      VoiceStartOutcome.started,
    );
    await Future<void>.delayed(const Duration(milliseconds: 30));

    expect(controller.state.phase, VoiceInputPhase.recording);
    expect(recorder.starts, 1);
    expect(recorder.stops, 0);
    expect(
      await controller.start(language: 'English', existingComposerText: ''),
      VoiceStartOutcome.busy,
    );
    expect(recorder.starts, 1);
  });

  test('explicit stop transcribes once and appends without auto-send',
      () async {
    final recorder = _FakeRecorder();
    final transcription = _FakeTranscription(['my head hurts']);
    final tempFiles = _FakeTempFiles();
    final controller = _controller(
      recorder: recorder,
      transcription: transcription,
      tempFiles: tempFiles,
    );
    addTearDown(controller.disposeAsync);

    await controller.start(
      language: 'English',
      existingComposerText: 'Since yesterday',
    );
    await controller.stopAndTranscribe();
    await controller.stopAndTranscribe();

    expect(recorder.stops, 1);
    expect(transcription.calls, 1);
    expect(controller.state.phase, VoiceInputPhase.ready);
    expect(controller.consumeTranscript(), 'Since yesterday my head hurts');
    expect(controller.state.phase, VoiceInputPhase.idle);
    expect(tempFiles.deleted, contains(recorder.path));
  });

  test('duration limit stops once and keeps the recording for transcription',
      () async {
    final recorder = _FakeRecorder();
    final transcription = _FakeTranscription();
    final controller = _controller(
      recorder: recorder,
      transcription: transcription,
      maximumDuration: const Duration(milliseconds: 25),
    );
    addTearDown(controller.disposeAsync);

    await controller.start(language: 'English', existingComposerText: '');
    await Future<void>.delayed(const Duration(milliseconds: 80));

    expect(recorder.stops, 1);
    expect(transcription.calls, 1);
    expect(controller.state.phase, VoiceInputPhase.ready);
  });

  test('cancel discards audio without transcription or composer mutation',
      () async {
    final recorder = _FakeRecorder();
    final transcription = _FakeTranscription();
    final tempFiles = _FakeTempFiles();
    final controller = _controller(
      recorder: recorder,
      transcription: transcription,
      tempFiles: tempFiles,
    );
    addTearDown(controller.disposeAsync);

    await controller.start(
      language: 'English',
      existingComposerText: 'keep this',
    );
    await controller.cancel();

    expect(recorder.cancels, 1);
    expect(transcription.calls, 0);
    expect(controller.consumeTranscript(), isNull);
    expect(tempFiles.deleted, contains(recorder.path));
  });

  test('recording language is captured and cannot change through another start',
      () async {
    final transcription = _FakeTranscription();
    final controller = _controller(transcription: transcription);
    addTearDown(controller.disposeAsync);

    await controller.start(
      language: 'Nigerian Pidgin',
      existingComposerText: '',
    );
    expect(
      await controller.start(language: 'English', existingComposerText: ''),
      VoiceStartOutcome.busy,
    );
    await controller.stopAndTranscribe();

    expect(transcription.language, 'pidgin');
    expect(controller.state.language, 'Nigerian Pidgin');
  });

  test('provider failure waits for explicit retry and retry makes one new call',
      () async {
    final transcription = _FakeTranscription([
      StateError('failed'),
      'retry transcript',
    ]);
    final controller = _controller(transcription: transcription);
    addTearDown(controller.disposeAsync);

    await controller.start(language: 'English', existingComposerText: '');
    await controller.stopAndTranscribe();
    expect(controller.state.phase, VoiceInputPhase.error);
    expect(controller.state.canRetry, isTrue);
    expect(transcription.calls, 1);

    await Future<void>.delayed(const Duration(milliseconds: 20));
    expect(transcription.calls, 1);
    await controller.retry();
    expect(transcription.calls, 2);
    expect(controller.state.phase, VoiceInputPhase.ready);
  });

  test('monthly voice limit keeps typed composer available and removes audio',
      () async {
    final transcription = _FakeTranscription(const [
      VoiceTranscriptionException(
        message: "You've used this month's voice input. "
            'You can still type your message.',
        canRetry: false,
      ),
    ]);
    final tempFiles = _FakeTempFiles();
    final controller = _controller(
      transcription: transcription,
      tempFiles: tempFiles,
    );
    addTearDown(controller.disposeAsync);

    await controller.start(
      language: 'English',
      existingComposerText: 'typed text',
    );
    await controller.stopAndTranscribe();

    expect(controller.state.phase, VoiceInputPhase.error);
    expect(controller.state.errorMessage, contains('still type'));
    expect(controller.state.canRetry, isFalse);
    expect(controller.state.locksComposer, isFalse);
    expect(tempFiles.deleted, contains('/tmp/mdq_voice_input_0.m4a'));
  });

  test('late provider completion after cancel cannot repopulate composer state',
      () async {
    final transcription = _FakeTranscription()..pending = Completer<String>();
    final controller = _controller(transcription: transcription);
    addTearDown(controller.disposeAsync);

    await controller.start(
        language: 'English', existingComposerText: 'new text');
    final stopFuture = controller.stopAndTranscribe();
    await Future<void>.delayed(Duration.zero);
    await controller.cancel();
    transcription.pending!.complete('late transcript');
    await stopFuture;

    expect(controller.state.phase, VoiceInputPhase.idle);
    expect(controller.consumeTranscript(), isNull);
  });

  test('permission outcomes are distinct and permanent denial opens settings',
      () async {
    final permission = _FakePermission()
      ..result = MicrophonePermissionResult.permanentlyDenied;
    final controller = _controller(permission: permission);
    addTearDown(controller.disposeAsync);

    expect(
      await controller.start(language: 'English', existingComposerText: ''),
      VoiceStartOutcome.permissionPermanentlyDenied,
    );
    expect(controller.state.phase, VoiceInputPhase.idle);
    expect(await controller.openPermissionSettings(), isTrue);
    expect(permission.settingsOpened, 1);

    permission.result = MicrophonePermissionResult.denied;
    expect(
      await controller.start(language: 'English', existingComposerText: ''),
      VoiceStartOutcome.permissionDenied,
    );
  });

  test('permission prompt is exposed and permission errors do not leave a lock',
      () async {
    final permission = _FakePermission()
      ..pending = Completer<MicrophonePermissionResult>();
    final controller = _controller(permission: permission);
    addTearDown(controller.disposeAsync);

    final start = controller.start(
      language: 'English',
      existingComposerText: '',
    );
    await Future<void>.delayed(Duration.zero);
    expect(controller.isRequestingMicrophonePermission, isTrue);

    permission.pending!.complete(MicrophonePermissionResult.granted);
    expect(await start, VoiceStartOutcome.started);
    expect(controller.isRequestingMicrophonePermission, isFalse);
    await controller.cancel();

    permission
      ..pending = null
      ..error = StateError('permission bridge failed');
    expect(
      await controller.start(
        language: 'English',
        existingComposerText: '',
      ),
      VoiceStartOutcome.failed,
    );
    expect(controller.isRequestingMicrophonePermission, isFalse);
    expect(controller.state.phase, VoiceInputPhase.error);
    expect(controller.state.errorMessage, contains('permission'));
  });

  test('recorder interruption cancels and never restarts automatically',
      () async {
    final recorder = _FakeRecorder();
    final controller = _controller(recorder: recorder);
    addTearDown(controller.disposeAsync);

    await controller.start(language: 'English', existingComposerText: '');
    recorder.controller.add(VoiceRecorderEvent.interrupted);
    await Future<void>.delayed(const Duration(milliseconds: 20));

    expect(controller.state.phase, VoiceInputPhase.idle);
    expect(recorder.cancels, 1);
    expect(recorder.starts, 1);
  });

  test('stale cleanup deletes only MDQ-owned M4A temp files', () async {
    final directory =
        await Directory.systemTemp.createTemp('mdq_cleanup_test_');
    addTearDown(() => directory.delete(recursive: true));
    final owned = File(
        '${directory.path}${Platform.pathSeparator}${mdqVoiceTempPrefix}stale.m4a');
    final unrelated =
        File('${directory.path}${Platform.pathSeparator}someone_else.m4a');
    final wrongExtension = File(
        '${directory.path}${Platform.pathSeparator}${mdqVoiceTempPrefix}notes.txt');
    await owned.writeAsBytes([1]);
    await unrelated.writeAsBytes([2]);
    await wrongExtension.writeAsBytes([3]);

    final store = VoiceTempFileStore(directoryProvider: () async => directory);
    await store.cleanupStale();

    expect(await owned.exists(), isFalse);
    expect(await unrelated.exists(), isTrue);
    expect(await wrongExtension.exists(), isTrue);
  });

  test('Dio transcription sends one multipart request with language and id',
      () async {
    final adapter = _CaptureAdapter();
    final dio = Dio(BaseOptions(baseUrl: 'https://local.test'))
      ..httpClientAdapter = adapter;
    final api = DioVoiceTranscriptionApi(dio);
    final directory = await Directory.systemTemp.createTemp('mdq_voice_test_');
    addTearDown(() => directory.delete(recursive: true));
    final file = File('${directory.path}${Platform.pathSeparator}fixture.m4a');
    await file.writeAsBytes([0, 1, 2]);

    expect(
      await api.transcribe(
        path: file.path,
        language: 'pidgin',
        requestId: 'request-123',
      ),
      'verbatim transcript',
    );
    final form = adapter.request!.data as FormData;
    expect(
      form.fields
          .any((field) => field.key == 'language' && field.value == 'pidgin'),
      isTrue,
    );
    expect(
      form.fields.any((field) =>
          field.key == 'request_identifier' && field.value == 'request-123'),
      isTrue,
    );
    expect(adapter.requests, 1);
  });

  test('Dio exposes backend monthly voice-limit message as non-retryable',
      () async {
    final adapter = _CaptureAdapter(
      statusCode: 429,
      responseData: {
        'detail': "You've used this month's voice input. "
            'You can still type your message.',
      },
    );
    final dio = Dio(BaseOptions(baseUrl: 'https://local.test'))
      ..httpClientAdapter = adapter;
    final api = DioVoiceTranscriptionApi(dio);
    final directory = await Directory.systemTemp.createTemp('mdq_limit_test_');
    addTearDown(() => directory.delete(recursive: true));
    final file = File('${directory.path}${Platform.pathSeparator}fixture.m4a');
    await file.writeAsBytes([0, 1, 2]);

    await expectLater(
      api.transcribe(
        path: file.path,
        language: 'english',
        requestId: 'request-limit',
      ),
      throwsA(
        isA<VoiceTranscriptionException>()
            .having((error) => error.canRetry, 'canRetry', isFalse)
            .having(
                (error) => error.message, 'message', contains('still type')),
      ),
    );
  });
}

class _CaptureAdapter implements HttpClientAdapter {
  final int statusCode;
  final Map<String, dynamic> responseData;
  RequestOptions? request;
  int requests = 0;

  _CaptureAdapter({
    this.statusCode = 200,
    this.responseData = const {'transcript': 'verbatim transcript'},
  });

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<List<int>>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    request = options;
    requests += 1;
    await requestStream?.drain<void>();
    return ResponseBody.fromString(
      jsonEncode(responseData),
      statusCode,
      headers: {
        Headers.contentTypeHeader: ['application/json'],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}
