import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http_parser/http_parser.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'package:mediq_app/src/core/api/api_error_mapper.dart';
import 'package:mediq_app/src/features/auth/presentation/user_controller.dart';
import 'package:mediq_app/src/features/chat/data/ai_pdf_attachment.dart';
import 'package:mediq_app/src/features/chat/data/ai_interaction.dart';
import 'package:mediq_app/src/features/lab/data/lab_result_model.dart';

@immutable
class AiChatContinuation {
  final String summaryId;
  final String sourceUpdatedAt;

  const AiChatContinuation({
    required this.summaryId,
    required this.sourceUpdatedAt,
  });

  @override
  bool operator ==(Object other) =>
      other is AiChatContinuation &&
      other.summaryId == summaryId &&
      other.sourceUpdatedAt == sourceUpdatedAt;

  @override
  int get hashCode => Object.hash(summaryId, sourceUpdatedAt);
}

// 1. STATE
enum AiRequestPhase {
  idle,
  sending,
  processing,
  delayed,
  succeeded,
  failed,
  cancelled,
}

class AiChatState {
  final List<Map<String, dynamic>> messages;
  final bool isLoading;
  final AiRequestPhase requestPhase;

  AiChatState({
    this.messages = const [],
    this.isLoading = false,
    this.requestPhase = AiRequestPhase.idle,
  });

  AiChatState copyWith(
      {List<Map<String, dynamic>>? messages,
      bool? isLoading,
      AiRequestPhase? requestPhase}) {
    return AiChatState(
      messages: messages ?? this.messages,
      isLoading: isLoading ?? this.isLoading,
      requestPhase: requestPhase ?? this.requestPhase,
    );
  }
}

// 2. CONTROLLER
class AiChatController extends StateNotifier<AiChatState> {
  final Dio _dio;
  final Duration operationPollInterval;
  String _subscriptionTier; // "free", "premium", or "family"
  final AiChatContinuation? continuation;
  String? _conversationMemory;
  String? _activeAssessmentId;
  int? _assessmentVersion;
  bool _assessmentReady = false;
  final List<String> _unsummarizedTurns = [];
  int _requestSequence = 0;
  String? _pendingSaveRequestId;
  ApiFailure? _lastSaveFailure;

  AiChatController(this._dio, this._subscriptionTier, this.continuation,
      {this.operationPollInterval = const Duration(seconds: 3)})
      : super(AiChatState());

  String? get sourceSummaryId => continuation?.summaryId;
  ApiFailure? get lastSaveFailure => _lastSaveFailure;
  bool get hasPaidContinuity =>
      {'premium', 'family'}.contains(_subscriptionTier);

  bool get hasActiveAssessment => _activeAssessmentId != null;
  bool get assessmentReady => _assessmentReady && _activeAssessmentId != null;

  Future<void> cancelAssessment() async {
    final id = _activeAssessmentId;
    final version = _assessmentVersion;
    if (state.isLoading || id == null || version == null) return;
    state = state.copyWith(isLoading: true);
    try {
      await _dio.post('/api/v1/chat/assessment/$id/cancel',
          data: {'expected_state_version': version},
          options: Options(headers: {'X-AI-Request-ID': _nextRequestId()}));
      if (!mounted) return;
      _activeAssessmentId = null;
      _assessmentVersion = null;
      _assessmentReady = false;
      state = state.copyWith(messages: [
        ...state.messages,
        {'role': 'system', 'message': 'Assessment ended.'}
      ], isLoading: false);
    } on DioException catch (error) {
      if (ApiErrorMapper.map(error).code == 'stale_version') {
        await restoreAssessment(force: true);
      } else if (mounted) {
        state = state.copyWith(isLoading: false);
      }
    }
  }

  Future<void> restoreAssessment({bool force = false}) async {
    if (!force && state.messages.isNotEmpty) return;
    try {
      final response = await _dio
          .get<Map<String, dynamic>>('/api/v1/chat/assessment/current');
      if (!mounted) return;
      final snapshot = response.data?['assessment'];
      if (snapshot is! Map) {
        if (force) {
          _activeAssessmentId = null;
          _assessmentVersion = null;
          _assessmentReady = false;
          state = state.copyWith(isLoading: false);
        }
        return;
      }
      final data = Map<String, dynamic>.from(snapshot);
      final status = data['status'];
      _activeAssessmentId = status == 'COMPLETED' || status == 'URGENT'
          ? null
          : data['assessment_id'] as String?;
      _assessmentVersion = data['state_version'] as int?;
      _assessmentReady = status == 'READY';
      final messages = <Map<String, dynamic>>[
        {'role': 'user', 'message': data['presenting_concern'] as String},
      ];
      for (final item in (data['questions'] as List? ?? const [])) {
        if (item is! Map) continue;
        final question = item['question'];
        if (question is String) {
          messages.add({
            'role': 'ai',
            'message': question,
            'interaction': AiAssessmentQuestionResult(question, true)
          });
        }
        final answer = item['answer'];
        if (answer is String && answer.isNotEmpty) {
          messages.add({'role': 'user', 'message': answer});
        }
      }
      final lastResponse = data['response'];
      if (lastResponse is Map) {
        final interaction = AiInteractionResponse.fromJson(
            Map<String, dynamic>.from(lastResponse));
        if (interaction.result is! AiAssessmentQuestionResult ||
            messages.length == 1) {
          messages.add({
            'role': 'ai',
            'message': interaction.result.visibleText,
            'interaction': interaction.result
          });
        }
      }
      state = state.copyWith(messages: [
        ...messages,
        if (_assessmentReady)
          {'role': 'system', 'message': 'This assessment is ready to finish.'},
      ], isLoading: false);
    } catch (_) {
      if (mounted && force) state = state.copyWith(isLoading: false);
    }
  }

  Future<void> finishAssessment() async {
    final id = _activeAssessmentId;
    final version = _assessmentVersion;
    if (state.isLoading || !_assessmentReady || id == null || version == null)
      return;
    state = state.copyWith(
        isLoading: true, requestPhase: AiRequestPhase.processing);
    final requestId = _nextRequestId();
    try {
      var response = await _dio.post('/api/v1/chat/analyze',
          data: {
            'message': '',
            'interaction_id': id,
            'expected_state_version': version
          },
          options: Options(headers: {'X-AI-Request-ID': requestId}));
      if (response.statusCode == 202)
        response = await _waitForChatOperation(requestId);
      _applyChatResponse(
          Map<String, dynamic>.from(response.data as Map), '', '', false);
    } on DioException catch (error) {
      if ({'stale_version', 'assessment_result_invalid'}
          .contains(ApiErrorMapper.map(error).code)) {
        await restoreAssessment(force: true);
      } else if (mounted) {
        state = state.copyWith(
            isLoading: false, requestPhase: AiRequestPhase.failed);
      }
    } catch (_) {
      if (mounted)
        state = state.copyWith(
            isLoading: false, requestPhase: AiRequestPhase.failed);
    }
  }

  /// Tier changes update policy for subsequent requests without replacing the
  /// in-memory conversation. Profile restoration is deliberately not a chat
  /// session lifecycle event.
  void updateSubscriptionTier(String tier) {
    if (tier.isNotEmpty) _subscriptionTier = tier;
  }

  Map<String, dynamic> get _continuationRequestFields => {
        if (continuation != null) ...{
          'source_summary_id': continuation!.summaryId,
          'source_summary_updated_at': continuation!.sourceUpdatedAt,
        },
      };

  Future<bool> hasActiveConsent() async {
    final response = await _dio.get('/api/v1/ai/consent/status');
    return response.data['consent_granted'] == true;
  }

  Future<bool> grantConsent() async {
    final response = await _dio.post('/api/v1/ai/consent');
    return response.data['consent_granted'] == true;
  }

  List<Map<String, dynamic>> _recentConversationHistory(
      {String? excludeId, int maxMessages = 10}) {
    final eligible = state.messages.where((message) {
      if (message['role'] == 'system') return false;
      if (excludeId != null && message['id'] == excludeId) return false;
      return message['role'] == 'user' || message['role'] == 'ai';
    }).toList();

    final recent = eligible.length > maxMessages
        ? eligible.sublist(eligible.length - maxMessages)
        : eligible;

    return recent
        .map((message) => {
              'role': message['role'] == 'user' ? 'patient' : 'mdq_plus',
              'parts': [(message['message'] ?? '').toString()],
            })
        .toList();
  }

  String? _olderUnsummarizedTurns() {
    if (_unsummarizedTurns.length <= 5) return null;
    return _unsummarizedTurns.take(_unsummarizedTurns.length - 5).join('\n\n');
  }

  List<Map<String, String>> _saveConversationTurns() {
    return state.messages
        .where(
            (message) => message['role'] == 'user' || message['role'] == 'ai')
        .map((message) => {
              'role': message['role'] == 'user' ? 'user' : 'assistant',
              'text': (message['message'] ?? '').toString(),
            })
        .toList();
  }

  String _nextRequestId() {
    _requestSequence += 1;
    return 'ai-${DateTime.now().microsecondsSinceEpoch}-$_requestSequence';
  }

  Future<Response<dynamic>> _waitForChatOperation(String requestId) async {
    for (var attempt = 0; attempt < 102; attempt++) {
      await Future<void>.delayed(operationPollInterval);
      if (!mounted) throw StateError('Chat screen was closed.');
      late final Response<Map<String, dynamic>> status;
      try {
        status = await _dio.get<Map<String, dynamic>>(
          '/api/v1/chat/request-status/$requestId',
        );
      } on DioException catch (error) {
        if (error.response?.statusCode == 401 ||
            error.response?.statusCode == 403) {
          rethrow;
        }
        continue;
      }
      final data = status.data ?? const <String, dynamic>{};
      if (data['status'] == 'succeeded' && data['response'] is Map) {
        return Response<dynamic>(
          requestOptions: status.requestOptions,
          data: data['response'],
          statusCode: 200,
        );
      }
      if (data['status'] == 'failed' || data['status'] == 'cancelled') {
        throw StateError('The request could not be completed.');
      }
    }
    throw StateError('The request status could not be confirmed.');
  }

  void _applyChatResponse(
    Map<String, dynamic> data,
    String tempId,
    String effectiveText,
    bool hasSessionMemory,
  ) {
    if (!mounted) return;
    final interaction = AiInteractionResponse.fromJson(data);
    final answer = interaction.result.visibleText;
    final memoryUpdate = interaction.memorySummary;
    final usageNotice = interaction.usageNotice;
    _activeAssessmentId = interaction.result is AiAssessmentQuestionResult
        ? interaction.assessmentId
        : null;
    _assessmentVersion = interaction.stateVersion;
    _assessmentReady = false;
    if (memoryUpdate != null && memoryUpdate.trim().isNotEmpty) {
      _conversationMemory = memoryUpdate.trim();
      _unsummarizedTurns.clear();
    } else if (hasSessionMemory) {
      _unsummarizedTurns.add('User: $effectiveText\nAssistant: $answer');
    }
    final messages = state.messages
        .map((message) => message['id'] == tempId
            ? (Map<String, dynamic>.from(message)..['isSending'] = false)
            : message)
        .toList();
    state = state.copyWith(
      messages: [
        ...messages,
        {'role': 'ai', 'message': answer, 'interaction': interaction.result},
        if (usageNotice != null)
          {'role': 'system', 'type': 'usage_notice', 'message': usageNotice},
      ],
      isLoading: false,
      requestPhase: AiRequestPhase.succeeded,
    );
  }

  Future<void> sendMessage(String text,
      {String? imageUrl,
      String? imagePublicId,
      String? imageFormat,
      AiPdfAttachment? document,
      String language = 'English'}) async {
    if (state.isLoading) return;
    if (imageUrl != null && document != null) return;
    if (text.trim().isEmpty && imageUrl == null && document == null) return;
    _pendingSaveRequestId = null;

    final effectiveText = text.trim().isNotEmpty
        ? text.trim()
        : document != null
            ? 'Analyse and explain this PDF document.'
            : text;

    final requestId = _nextRequestId();
    final tempId = requestId;
    final userMsg = {
      'id': tempId,
      'role': 'user',
      'message': effectiveText,
      'image': imageUrl,
      'documentName': document?.name,
      'isSending': true
    };
    state = state.copyWith(
      messages: [...state.messages, userMsg],
      isLoading: true,
      requestPhase: AiRequestPhase.sending,
    );

    try {
      // Free keeps shallow session history; paid tiers also receive rolling memory.
      final hasSessionMemory = hasPaidContinuity;
      final history = _recentConversationHistory(
        excludeId: tempId,
        maxMessages: hasSessionMemory ? 10 : 4,
      );
      final shouldUpdateMemory =
          hasSessionMemory && _unsummarizedTurns.length >= 7;
      final olderTurnsLeavingWindow =
          shouldUpdateMemory ? _olderUnsummarizedTurns() : null;

      // Connects to your backend
      final requestData = {
        "message": effectiveText,
        if (_activeAssessmentId != null) "interaction_id": _activeAssessmentId,
        if (_activeAssessmentId != null)
          "expected_state_version": _assessmentVersion,
        "history": history,
        "language": language,
        if (hasSessionMemory) ...{
          "conversation_memory": _conversationMemory,
          "memory_source": olderTurnsLeavingWindow,
          "update_memory": shouldUpdateMemory,
        },
        ..._continuationRequestFields,
      };
      late Response<dynamic> response;
      state = state.copyWith(requestPhase: AiRequestPhase.processing);
      if (document != null) {
        response = await _dio.post(
          '/api/v1/chat/analyze-document',
          data: FormData.fromMap({
            ...requestData,
            'history': jsonEncode(history),
            'file': MultipartFile.fromBytes(
              document.bytes,
              filename: document.name,
              contentType: MediaType('application', 'pdf'),
            ),
          }),
          options: Options(headers: {'X-AI-Request-ID': requestId}),
        );
      } else {
        response = await _dio.post(
          '/api/v1/chat/analyze',
          data: {
            ...requestData,
            "image_url": imageUrl,
            "image_public_id": imagePublicId,
            "image_format": imageFormat,
          },
          options: Options(headers: {'X-AI-Request-ID': requestId}),
        );
      }

      if (response.statusCode == 202) {
        state = state.copyWith(requestPhase: AiRequestPhase.delayed);
        response = await _waitForChatOperation(requestId);
      }

      _applyChatResponse(
        Map<String, dynamic>.from(response.data as Map),
        tempId,
        effectiveText,
        hasSessionMemory,
      );
    } on DioException catch (e) {
      final failure = ApiErrorMapper.map(e);
      if ({'stale_version', 'assessment_result_invalid'}
          .contains(failure.code)) {
        if (mounted) {
          state = state.copyWith(
              messages: state.messages
                  .where((message) => message['id'] != tempId)
                  .toList(),
              isLoading: false,
              requestPhase: AiRequestPhase.failed);
        }
        await restoreAssessment(force: true);
        return;
      }
      if (failure.kind == ApiFailureKind.timeout) {
        try {
          state = state.copyWith(requestPhase: AiRequestPhase.delayed);
          final recovered = await _waitForChatOperation(requestId);
          _applyChatResponse(
            Map<String, dynamic>.from(recovered.data as Map),
            tempId,
            effectiveText,
            hasPaidContinuity,
          );
          return;
        } catch (_) {
          // The operation reached a terminal failure or its lease expired.
        }
      }
      if (!failure.shouldPresent) {
        if (!mounted) return;
        final newMessages = state.messages.map((message) {
          if (message['id'] != tempId) return message;
          return Map<String, dynamic>.from(message)..['isSending'] = false;
        }).toList();
        state = state.copyWith(
          messages: newMessages,
          isLoading: false,
          requestPhase: AiRequestPhase.cancelled,
        );
        return;
      }
      String errorMessage = failure.message;

      // PDF/provider failures get a stable message. Quota and ownership
      // responses remain actionable without exposing implementation details.
      if (document != null) {
        if (failure.statusCode == 413) {
          errorMessage = 'PDFs must be 8 MB or smaller.';
        } else if (failure.kind == ApiFailureKind.rateLimited) {
          errorMessage = failure.message;
        } else if (failure.statusCode == 404 && sourceSummaryId != null) {
          errorMessage = 'This saved conversation is no longer available.';
        } else if (failure.kind != ApiFailureKind.offline &&
            failure.kind != ApiFailureKind.timeout &&
            failure.kind != ApiFailureKind.serverUnavailable) {
          errorMessage =
              'This PDF could not be processed. Please choose a valid PDF and try again.';
        }
      }

      final errorMsg = {'role': 'system', 'message': errorMessage};
      if (!mounted) return;

      final newMessages = state.messages.map((m) {
        if (m['id'] == tempId) {
          final newM = Map<String, dynamic>.from(m);
          newM['isSending'] = false;
          return newM;
        }
        return m;
      }).toList();

      state = state.copyWith(
          messages: [...newMessages, errorMsg],
          isLoading: false,
          requestPhase: AiRequestPhase.failed);
    } catch (_) {
      debugPrint('[AiChatController] AI request failed.');
      final errorMsg = {
        'role': 'system',
        'message': 'AI service is temporarily unavailable. Please try again.'
      };
      if (!mounted) return;

      final newMessages = state.messages.map((m) {
        if (m['id'] == tempId) {
          final newM = Map<String, dynamic>.from(m);
          newM['isSending'] = false;
          return newM;
        }
        return m;
      }).toList();

      state = state.copyWith(
          messages: [...newMessages, errorMsg],
          isLoading: false,
          requestPhase: AiRequestPhase.failed);
    } finally {
      if (imagePublicId != null) {
        await deleteTemporaryImage(imagePublicId);
      }
    }
  }

  Future<void> deleteTemporaryImage(String publicId) async {
    try {
      await _dio.delete(
        '/api/v1/chat/image',
        queryParameters: {'public_id': publicId},
      );
    } catch (_) {
      debugPrint('[AiChatController] temporary image cleanup failed.');
    }
  }

  /// Reports a specific AI-generated message to the backend.
  ///
  /// This is a side-effect-only call — it does not mutate [AiChatState].
  /// Throws an [AppException] on failure so the caller (UI) can show an error.
  Future<void> reportMessage(String messageText, String reason) async {
    await _dio.post(
      '/api/v1/chat/report',
      data: {
        'message_text': messageText,
        'reason': reason,
      },
    );
  }

  Future<void> sendLabResult(LabAnalysisResponse result) async {
    if (state.isLoading) return;
    if (result.recordId == null) return;
    _pendingSaveRequestId = null;
    final requestId = _nextRequestId();

    // 1. Create a "Medical Card" message for the user's UI
    final userMsg = {
      'role': 'user',
      'message': 'Lab Result Scanned',
      'type': 'lab_result',
      'lab_data': result, // Store full object for bubble rendering
    };

    // Add to local state immediately
    state = state.copyWith(
      messages: [...state.messages, userMsg],
      isLoading: true,
      requestPhase: AiRequestPhase.sending,
    );

    try {
      late Response<dynamic> response;
      state = state.copyWith(requestPhase: AiRequestPhase.processing);
      try {
        response = await _dio.post('/api/v1/chat/analyze',
            data: {
              "message": "Explain this urinalysis result.",
              "lab_result_id": result.recordId,
              if (_activeAssessmentId != null) ...{
                "interaction_id": _activeAssessmentId,
                "expected_state_version": _assessmentVersion,
              },
              "history": _recentConversationHistory(
                maxMessages: hasPaidContinuity ? 10 : 4,
              ),
              if (hasPaidContinuity) ...{
                "conversation_memory": _conversationMemory,
                "memory_source": _olderUnsummarizedTurns(),
                "update_memory": false,
              },
              ..._continuationRequestFields,
            },
            options: Options(headers: {'X-AI-Request-ID': requestId}));
      } on DioException catch (error) {
        if (ApiErrorMapper.map(error).kind != ApiFailureKind.timeout) rethrow;
        state = state.copyWith(requestPhase: AiRequestPhase.delayed);
        response = await _waitForChatOperation(requestId);
      }
      if (response.statusCode == 202) {
        state = state.copyWith(requestPhase: AiRequestPhase.delayed);
        response = await _waitForChatOperation(requestId);
      }
      _applyChatResponse(Map<String, dynamic>.from(response.data as Map),
          requestId, 'Explain this urinalysis result.', hasPaidContinuity);
    } catch (_) {
      debugPrint('[AiChatController] lab-result analysis failed.');
      final errorMsg = {
        'role': 'system',
        'message': 'AI analysis is temporarily unavailable. Please try again.'
      };
      if (!mounted) return;
      state = state.copyWith(
        messages: [...state.messages, errorMsg],
        isLoading: false,
        requestPhase: AiRequestPhase.failed,
      );
    }
  }

  /// Sends typed ephemeral turns to the backend-owned Vault summary operation.
  /// Returns [true] if the save was successful, [false] otherwise.
  Future<bool> saveSummary() async {
    if (!mounted) return false;
    if (!hasPaidContinuity) return false;
    if (state.isLoading) return false;
    state = state.copyWith(isLoading: true);
    _lastSaveFailure = null;

    try {
      _pendingSaveRequestId ??= _nextRequestId();
      await _dio.post(
        '/api/v1/vault/ai-summary/save',
        data: {
          'turns': _saveConversationTurns(),
          if (continuation != null) ...{
            'source_summary_id': continuation!.summaryId,
            'source_updated_at': continuation!.sourceUpdatedAt,
          },
        },
        options: Options(
          headers: {'X-AI-Request-ID': _pendingSaveRequestId},
        ),
      );

      if (!mounted) return false;
      state = state.copyWith(isLoading: false);
      return true;
    } on DioException catch (e) {
      _lastSaveFailure = ApiErrorMapper.map(e);
      debugPrint(
        '[AiChatController] summary save failed '
        'status=${_lastSaveFailure?.statusCode} code=${_lastSaveFailure?.code}.',
      );
      if (!mounted) return false;
      state = state.copyWith(isLoading: false);
      return false;
    } catch (e) {
      _lastSaveFailure = ApiErrorMapper.map(e);
      debugPrint('[AiChatController] summary save failed unexpectedly.');
      if (!mounted) return false;
      state = state.copyWith(isLoading: false);
      return false;
    }
  }
}

// 3. PROVIDER
// autoDispose wipes an unsaved session only when its route is genuinely left.
// Profile refreshes update policy in-place and must not recreate this notifier.
final aiChatControllerProvider = StateNotifierProvider.autoDispose
    .family<AiChatController, AiChatState, AiChatContinuation?>(
        (ref, continuation) {
  final dio = ref.watch(dioProvider);

  // Read once for construction. A listener applies later profile/tier changes
  // without making userProvider a provider-recreation dependency.
  final userAsync = ref.read(userProvider);
  final tier = userAsync.value?.subscriptionTier ?? 'free';
  final controller = AiChatController(dio, tier, continuation);
  if (kDebugMode) {
    debugPrint(
      '[AI SESSION] created continuation=${continuation != null}',
    );
  }
  ref.listen(userProvider, (_, next) {
    final refreshedTier = next.valueOrNull?.subscriptionTier;
    if (refreshedTier != null) {
      controller.updateSubscriptionTier(refreshedTier);
    }
  });
  ref.onDispose(() {
    if (kDebugMode) debugPrint('[AI SESSION] disposed');
  });

  return controller;
});
