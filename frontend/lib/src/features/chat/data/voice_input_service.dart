import 'dart:async';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:http_parser/http_parser.dart';
import 'package:path_provider/path_provider.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:record/record.dart';
import 'package:uuid/uuid.dart';

const mdqVoiceTempPrefix = 'mdq_voice_input_';
const mdqVoiceMimeType = 'audio/mp4';
const mdqVoiceBitRate = 64000;
const mdqVoiceSampleRate = 16000;
const mdqVoiceChannels = 1;

enum MicrophonePermissionResult { granted, denied, permanentlyDenied }

abstract interface class MicrophonePermissionPort {
  Future<MicrophonePermissionResult> request();
  Future<bool> openSettings();
}

class PermissionHandlerMicrophonePermission
    implements MicrophonePermissionPort {
  @override
  Future<MicrophonePermissionResult> request() async {
    var status = await Permission.microphone.status;
    if (status.isDenied) {
      status = await Permission.microphone.request();
    }
    if (status.isGranted) return MicrophonePermissionResult.granted;
    if (status.isPermanentlyDenied) {
      return MicrophonePermissionResult.permanentlyDenied;
    }
    return MicrophonePermissionResult.denied;
  }

  @override
  Future<bool> openSettings() => openAppSettings();
}

enum VoiceRecorderEvent { recording, interrupted, stopped }

abstract interface class VoiceRecorderPort {
  Stream<VoiceRecorderEvent> get events;
  Future<void> start(String path);
  Future<String?> stop();
  Future<void> cancel();
  Future<void> dispose();
}

class RecordVoiceRecorder implements VoiceRecorderPort {
  final AudioRecorder _recorder;

  RecordVoiceRecorder({AudioRecorder? recorder})
      : _recorder = recorder ?? AudioRecorder();

  @override
  Stream<VoiceRecorderEvent> get events =>
      _recorder.onStateChanged().map((state) {
        switch (state) {
          case RecordState.record:
            return VoiceRecorderEvent.recording;
          case RecordState.pause:
            return VoiceRecorderEvent.interrupted;
          case RecordState.stop:
            return VoiceRecorderEvent.stopped;
        }
      });

  @override
  Future<void> start(String path) => _recorder.start(
        const RecordConfig(
          encoder: AudioEncoder.aacLc,
          bitRate: mdqVoiceBitRate,
          sampleRate: mdqVoiceSampleRate,
          numChannels: mdqVoiceChannels,
          audioInterruption: AudioInterruptionMode.pause,
        ),
        path: path,
      );

  @override
  Future<String?> stop() => _recorder.stop();

  @override
  Future<void> cancel() => _recorder.cancel();

  @override
  Future<void> dispose() => _recorder.dispose();
}

abstract interface class VoiceTempFilePort {
  Future<void> cleanupStale();
  Future<String> createPath();
  Future<void> delete(String? path);
}

class VoiceTempFileStore implements VoiceTempFilePort {
  final Future<Directory> Function() _directoryProvider;

  VoiceTempFileStore({Future<Directory> Function()? directoryProvider})
      : _directoryProvider = directoryProvider ?? getTemporaryDirectory;

  @override
  Future<void> cleanupStale() async {
    final directory = await _directoryProvider();
    await for (final entity in directory.list(followLinks: false)) {
      if (entity is! File) continue;
      final name = entity.uri.pathSegments.last;
      if (name.startsWith(mdqVoiceTempPrefix) && name.endsWith('.m4a')) {
        try {
          await entity.delete();
        } on FileSystemException {
          // A platform recorder may still be releasing a crashed/stale file.
        }
      }
    }
  }

  @override
  Future<String> createPath() async {
    final directory = await _directoryProvider();
    return '${directory.path}${Platform.pathSeparator}'
        '$mdqVoiceTempPrefix${const Uuid().v4()}.m4a';
  }

  @override
  Future<void> delete(String? path) async {
    if (path == null || path.isEmpty) return;
    final file = File(path);
    try {
      if (await file.exists()) await file.delete();
    } on FileSystemException {
      // Best-effort cleanup is retried by the next stale-file sweep.
    }
  }
}

abstract interface class VoiceTranscriptionPort {
  Future<String> transcribe({
    required String path,
    required String language,
    required String requestId,
  });
  Future<void> cancelActive();
}

class VoiceTranscriptionException implements Exception {
  final String message;
  final bool canRetry;

  const VoiceTranscriptionException({
    required this.message,
    required this.canRetry,
  });

  @override
  String toString() => message;
}

class DioVoiceTranscriptionApi implements VoiceTranscriptionPort {
  final Dio _dio;
  CancelToken? _cancelToken;

  DioVoiceTranscriptionApi(this._dio);

  @override
  Future<String> transcribe({
    required String path,
    required String language,
    required String requestId,
  }) async {
    if (_cancelToken != null) {
      throw StateError('A transcription request is already active.');
    }
    final cancelToken = CancelToken();
    _cancelToken = cancelToken;
    try {
      final response = await _dio.post<Map<String, dynamic>>(
        '/api/v1/voice/transcribe',
        data: FormData.fromMap({
          'language': language,
          'request_identifier': requestId,
          'file': await MultipartFile.fromFile(
            path,
            filename: 'mdq_voice.m4a',
            contentType: MediaType('audio', 'mp4'),
          ),
        }),
        options: Options(
          contentType: 'multipart/form-data',
          receiveTimeout: const Duration(seconds: 90),
          sendTimeout: const Duration(seconds: 45),
        ),
        cancelToken: cancelToken,
      );
      final transcript = response.data?['transcript']?.toString().trim() ?? '';
      if (transcript.isEmpty) {
        throw StateError('The transcription service returned no speech.');
      }
      return transcript;
    } on DioException catch (error) {
      if (error.response?.statusCode == 429) {
        final data = error.response?.data;
        final detail = data is Map
            ? (data['detail'] ?? data['error'])?.toString().trim()
            : null;
        throw VoiceTranscriptionException(
          message: detail == null || detail.isEmpty
              ? 'Voice input is temporarily limited. '
                  'You can still type your message.'
              : detail,
          canRetry: false,
        );
      }
      rethrow;
    } finally {
      if (identical(_cancelToken, cancelToken)) _cancelToken = null;
    }
  }

  @override
  Future<void> cancelActive() async {
    _cancelToken?.cancel('Voice transcription cancelled by the user.');
    _cancelToken = null;
  }
}
