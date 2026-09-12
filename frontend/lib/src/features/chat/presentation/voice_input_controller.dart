import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:uuid/uuid.dart';

import '../data/voice_input_capability.dart';
import '../data/voice_input_service.dart';

enum VoiceInputPhase {
  idle,
  starting,
  recording,
  stopping,
  transcribing,
  ready,
  error,
}

enum VoiceStartOutcome {
  started,
  busy,
  unsupportedLanguage,
  permissionDenied,
  permissionPermanentlyDenied,
  failed,
}

@immutable
class VoiceInputState {
  final VoiceInputPhase phase;
  final Duration elapsed;
  final String? language;
  final String? transcript;
  final String? errorMessage;
  final bool canRetry;

  const VoiceInputState({
    this.phase = VoiceInputPhase.idle,
    this.elapsed = Duration.zero,
    this.language,
    this.transcript,
    this.errorMessage,
    this.canRetry = false,
  });

  bool get locksComposer => switch (phase) {
        VoiceInputPhase.starting ||
        VoiceInputPhase.recording ||
        VoiceInputPhase.stopping ||
        VoiceInputPhase.transcribing =>
          true,
        VoiceInputPhase.error => canRetry,
        VoiceInputPhase.idle || VoiceInputPhase.ready => false,
      };

  bool get locksLanguage => locksComposer;
}

class VoiceInputController extends ChangeNotifier {
  final VoiceRecorderPort _recorder;
  final VoiceTranscriptionPort _transcription;
  final VoiceTempFilePort _tempFiles;
  final MicrophonePermissionPort _permission;
  final Duration maximumDuration;
  final Duration timerInterval;

  VoiceInputState _state = const VoiceInputState();
  VoiceInputState get state => _state;

  StreamSubscription<VoiceRecorderEvent>? _recorderEvents;
  Future<void>? _initialization;
  Timer? _timer;
  Stopwatch? _stopwatch;
  String? _audioPath;
  String _composerSnapshot = '';
  int _operation = 0;
  bool _expectedRecorderStop = false;
  bool _requestingMicrophonePermission = false;
  bool _disposed = false;

  bool get isRequestingMicrophonePermission => _requestingMicrophonePermission;

  VoiceInputController({
    required VoiceRecorderPort recorder,
    required VoiceTranscriptionPort transcription,
    required VoiceTempFilePort tempFiles,
    required MicrophonePermissionPort permission,
    this.maximumDuration = const Duration(seconds: 90),
    this.timerInterval = const Duration(seconds: 1),
  })  : _recorder = recorder,
        _transcription = transcription,
        _tempFiles = tempFiles,
        _permission = permission {
    _recorderEvents = _recorder.events.listen(_handleRecorderEvent);
  }

  Future<void> initialize() => _initialization ??= _runInitialization();

  Future<void> _runInitialization() async {
    try {
      await _tempFiles.cleanupStale();
    } catch (_) {
      // Startup cleanup is best effort and never blocks the AI chat screen.
    }
  }

  Future<VoiceStartOutcome> start({
    required String language,
    required String existingComposerText,
  }) async {
    if (_state.phase != VoiceInputPhase.idle) {
      return VoiceStartOutcome.busy;
    }
    final capability = aiLanguageCapabilityFor(language);
    if (!capability.voiceInputEnabled) {
      return VoiceStartOutcome.unsupportedLanguage;
    }

    final operation = ++_operation;
    _setState(VoiceInputState(
      phase: VoiceInputPhase.starting,
      language: language,
    ));
    await initialize();
    if (!_isCurrent(operation)) return VoiceStartOutcome.failed;
    late final MicrophonePermissionResult permission;
    _requestingMicrophonePermission = true;
    try {
      permission = await _permission.request();
    } catch (_) {
      if (_isCurrent(operation)) {
        _setState(const VoiceInputState(
          phase: VoiceInputPhase.error,
          errorMessage: 'Microphone permission could not be checked.',
        ));
      }
      return VoiceStartOutcome.failed;
    } finally {
      _requestingMicrophonePermission = false;
    }
    if (!_isCurrent(operation)) return VoiceStartOutcome.failed;
    if (permission == MicrophonePermissionResult.denied) {
      _setState(const VoiceInputState());
      return VoiceStartOutcome.permissionDenied;
    }
    if (permission == MicrophonePermissionResult.permanentlyDenied) {
      _setState(const VoiceInputState());
      return VoiceStartOutcome.permissionPermanentlyDenied;
    }

    await _tempFiles.delete(_audioPath);
    final path = await _tempFiles.createPath();
    _audioPath = path;
    if (!_isCurrent(operation)) {
      await _tempFiles.delete(path);
      if (_audioPath == path) _audioPath = null;
      return VoiceStartOutcome.failed;
    }
    _composerSnapshot = existingComposerText;
    try {
      await _recorder.start(path);
      if (!_isCurrent(operation)) {
        await _recorder.cancel();
        await _tempFiles.delete(path);
        if (_audioPath == path) _audioPath = null;
        return VoiceStartOutcome.failed;
      }
      _stopwatch = Stopwatch()..start();
      _setState(VoiceInputState(
        phase: VoiceInputPhase.recording,
        language: language,
      ));
      _timer = Timer.periodic(timerInterval, (_) => _updateElapsed(operation));
      return VoiceStartOutcome.started;
    } catch (_) {
      await _tempFiles.delete(path);
      if (_audioPath == path) _audioPath = null;
      if (!_isCurrent(operation)) return VoiceStartOutcome.failed;
      _setState(const VoiceInputState(
        phase: VoiceInputPhase.error,
        errorMessage: 'Recording could not start. Please try again.',
      ));
      return VoiceStartOutcome.failed;
    }
  }

  void _updateElapsed(int operation) {
    if (!_isCurrent(operation) || _state.phase != VoiceInputPhase.recording) {
      return;
    }
    final elapsed = _stopwatch?.elapsed ?? Duration.zero;
    _setState(VoiceInputState(
      phase: VoiceInputPhase.recording,
      elapsed: elapsed > maximumDuration ? maximumDuration : elapsed,
      language: _state.language,
    ));
    if (elapsed >= maximumDuration) {
      unawaited(stopAndTranscribe());
    }
  }

  Future<void> stopAndTranscribe() async {
    if (_state.phase != VoiceInputPhase.recording) return;
    final operation = _operation;
    _stopTimer();
    _setState(VoiceInputState(
      phase: VoiceInputPhase.stopping,
      elapsed: _boundedElapsed,
      language: _state.language,
    ));

    try {
      _expectedRecorderStop = true;
      final completedPath = await _recorder.stop();
      _expectedRecorderStop = false;
      if (!_isCurrent(operation)) return;
      if (completedPath != null && completedPath.isNotEmpty) {
        _audioPath = completedPath;
      }
      await _transcribeCurrent(operation);
    } catch (_) {
      _expectedRecorderStop = false;
      if (!_isCurrent(operation)) return;
      _setState(VoiceInputState(
        phase: VoiceInputPhase.error,
        elapsed: _boundedElapsed,
        language: _state.language,
        errorMessage: 'Recording could not be completed. Cancel and try again.',
      ));
    }
  }

  Future<void> _transcribeCurrent(int operation) async {
    final path = _audioPath;
    final language = _state.language;
    if (path == null || language == null) {
      _setState(const VoiceInputState(
        phase: VoiceInputPhase.error,
        errorMessage: 'No recording was available to transcribe.',
      ));
      return;
    }
    _setState(VoiceInputState(
      phase: VoiceInputPhase.transcribing,
      elapsed: _boundedElapsed,
      language: language,
    ));
    try {
      final transcript = await _transcription.transcribe(
        path: path,
        language: aiLanguageCapabilityFor(language).apiValue,
        requestId: const Uuid().v4(),
      );
      if (!_isCurrent(operation)) return;
      await _tempFiles.delete(path);
      _audioPath = null;
      _setState(VoiceInputState(
        phase: VoiceInputPhase.ready,
        elapsed: _boundedElapsed,
        language: language,
        transcript: transcript,
      ));
    } on VoiceTranscriptionException catch (error) {
      if (!_isCurrent(operation)) return;
      if (!error.canRetry) {
        await _tempFiles.delete(path);
        _audioPath = null;
      }
      _setState(VoiceInputState(
        phase: VoiceInputPhase.error,
        elapsed: _boundedElapsed,
        language: language,
        errorMessage: error.message,
        canRetry: error.canRetry,
      ));
    } catch (_) {
      if (!_isCurrent(operation)) return;
      _setState(VoiceInputState(
        phase: VoiceInputPhase.error,
        elapsed: _boundedElapsed,
        language: language,
        errorMessage:
            'We could not transcribe this recording. Retry or cancel it.',
        canRetry: true,
      ));
    }
  }

  Future<void> retry() async {
    if (_state.phase != VoiceInputPhase.error ||
        !_state.canRetry ||
        _audioPath == null) {
      return;
    }
    final operation = ++_operation;
    await _transcribeCurrent(operation);
  }

  String? consumeTranscript() {
    if (_state.phase != VoiceInputPhase.ready || _state.transcript == null) {
      return null;
    }
    final before = _composerSnapshot.trim();
    final transcript = _state.transcript!.trim();
    final combined = before.isEmpty
        ? transcript
        : transcript.isEmpty
            ? before
            : '$before $transcript';
    _composerSnapshot = '';
    _state = const VoiceInputState();
    return combined;
  }

  Future<void> cancel() async {
    final priorPhase = _state.phase;
    final path = _audioPath;
    ++_operation;
    _stopTimer();
    _expectedRecorderStop = true;
    try {
      await _transcription.cancelActive();
      if (priorPhase == VoiceInputPhase.recording ||
          priorPhase == VoiceInputPhase.stopping) {
        await _recorder.cancel();
      }
    } finally {
      _expectedRecorderStop = false;
      await _tempFiles.delete(path);
      _audioPath = null;
      _composerSnapshot = '';
      if (!_disposed) _setState(const VoiceInputState());
    }
  }

  Future<void> interrupt() async {
    if (_state.phase == VoiceInputPhase.idle ||
        _state.phase == VoiceInputPhase.ready) {
      return;
    }
    await cancel();
  }

  Future<bool> openPermissionSettings() => _permission.openSettings();

  void _handleRecorderEvent(VoiceRecorderEvent event) {
    if (_expectedRecorderStop || _state.phase != VoiceInputPhase.recording) {
      return;
    }
    if (event == VoiceRecorderEvent.interrupted ||
        event == VoiceRecorderEvent.stopped) {
      unawaited(interrupt());
    }
  }

  Duration get _boundedElapsed {
    final elapsed = _stopwatch?.elapsed ?? _state.elapsed;
    return elapsed > maximumDuration ? maximumDuration : elapsed;
  }

  void _stopTimer() {
    _timer?.cancel();
    _timer = null;
    _stopwatch?.stop();
  }

  bool _isCurrent(int operation) => !_disposed && operation == _operation;

  void _setState(VoiceInputState value) {
    if (_disposed) return;
    _state = value;
    notifyListeners();
  }

  Future<void> disposeAsync() async {
    if (_disposed) return;
    await cancel();
    _disposed = true;
    await _recorderEvents?.cancel();
    await _recorder.dispose();
    super.dispose();
  }
}
