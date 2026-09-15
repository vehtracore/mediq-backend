import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http_parser/http_parser.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'package:mediq_app/src/core/api/api_error_mapper.dart';
import 'package:mediq_app/src/features/auth/presentation/user_controller.dart';
import 'package:mediq_app/src/features/chat/data/ai_pdf_attachment.dart';
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
class AiChatState {
  final List<Map<String, dynamic>> messages;
  final bool isLoading;

  AiChatState({this.messages = const [], this.isLoading = false});

  AiChatState copyWith(
      {List<Map<String, dynamic>>? messages, bool? isLoading}) {
    return AiChatState(
      messages: messages ?? this.messages,
      isLoading: isLoading ?? this.isLoading,
    );
  }
}

// 2. CONTROLLER
class AiChatController extends StateNotifier<AiChatState> {
  final Dio _dio;
  String _subscriptionTier; // "free", "premium", or "family"
  final AiChatContinuation? continuation;
  String? _conversationMemory;
  final List<String> _unsummarizedTurns = [];
  int _requestSequence = 0;
  String? _pendingSaveRequestId;
  ApiFailure? _lastSaveFailure;

  AiChatController(this._dio, this._subscriptionTier, this.continuation)
      : super(AiChatState());

  String? get sourceSummaryId => continuation?.summaryId;
  ApiFailure? get lastSaveFailure => _lastSaveFailure;
  bool get hasPaidContinuity =>
      {'premium', 'family'}.contains(_subscriptionTier);

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

  List<Map<String, dynamic>> _recentGeminiHistory(
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
              'role': message['role'] == 'user' ? 'user' : 'model',
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
    state =
        state.copyWith(messages: [...state.messages, userMsg], isLoading: true);

    try {
      // Free keeps shallow session history; paid tiers also receive rolling memory.
      final hasSessionMemory = hasPaidContinuity;
      final history = _recentGeminiHistory(
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
        "history": history,
        "language": language,
        if (hasSessionMemory) ...{
          "conversation_memory": _conversationMemory,
          "memory_source": olderTurnsLeavingWindow,
          "update_memory": shouldUpdateMemory,
        },
        ..._continuationRequestFields,
      };
      late final Response<dynamic> response;
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

      final aiMsg = {'role': 'ai', 'message': response.data['response']};
      final memoryUpdate = response.data['memory_summary'] as String?;
      final usageNotice = response.data['usage_notice'] as String?;
      final noticeMsg = usageNotice == null
          ? null
          : {
              'role': 'system',
              'type': 'usage_notice',
              'message': usageNotice,
            };
      if (!mounted) return;
      if (memoryUpdate != null && memoryUpdate.trim().isNotEmpty) {
        _conversationMemory = memoryUpdate.trim();
        _unsummarizedTurns.clear();
      } else if (hasSessionMemory) {
        _unsummarizedTurns.add(
          'User: $effectiveText\nAssistant: ${response.data['response']}',
        );
      }

      final newMessages = state.messages.map((m) {
        if (m['id'] == tempId) {
          final newM = Map<String, dynamic>.from(m);
          newM['isSending'] = false;
          return newM;
        }
        return m;
      }).toList();

      state = state.copyWith(
        messages: [
          ...newMessages,
          aiMsg,
          if (noticeMsg != null) noticeMsg,
        ],
        isLoading: false,
      );
    } on DioException catch (e) {
      final failure = ApiErrorMapper.map(e);
      if (!failure.shouldPresent) {
        if (!mounted) return;
        final newMessages = state.messages.map((message) {
          if (message['id'] != tempId) return message;
          return Map<String, dynamic>.from(message)..['isSending'] = false;
        }).toList();
        state = state.copyWith(messages: newMessages, isLoading: false);
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

      state = state
          .copyWith(messages: [...newMessages, errorMsg], isLoading: false);
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

      state = state
          .copyWith(messages: [...newMessages, errorMsg], isLoading: false);
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
    _pendingSaveRequestId = null;

    // 1. Create a "Medical Card" message for the user's UI
    final userMsg = {
      'role': 'user',
      'message': 'Lab Result Scanned',
      'type': 'lab_result',
      'lab_data': result, // Store full object for bubble rendering
    };

    // Add to local state immediately
    state =
        state.copyWith(messages: [...state.messages, userMsg], isLoading: true);

    // 2. Construct the Hidden System Prompt for Gemini
    final hiddenPrompt = _buildSystemPrompt(result);

    try {
      // Connects to your backend
      final response = await _dio.post('/api/v1/chat/analyze',
          data: {
            "message": hiddenPrompt,
            "history": _recentGeminiHistory(
              maxMessages: hasPaidContinuity ? 10 : 4,
            ),
            if (hasPaidContinuity) ...{
              "conversation_memory": _conversationMemory,
              "memory_source": _olderUnsummarizedTurns(),
              "update_memory": false,
            },
            ..._continuationRequestFields,
          },
          options: Options(headers: {'X-AI-Request-ID': _nextRequestId()}));

      final aiMsg = {'role': 'ai', 'message': response.data['response']};
      if (!mounted) return;
      state = state
          .copyWith(messages: [...state.messages, aiMsg], isLoading: false);
    } catch (_) {
      debugPrint('[AiChatController] lab-result analysis failed.');
      final errorMsg = {
        'role': 'system',
        'message': 'AI analysis is temporarily unavailable. Please try again.'
      };
      if (!mounted) return;
      state = state
          .copyWith(messages: [...state.messages, errorMsg], isLoading: false);
    }
  }

  String _buildSystemPrompt(LabAnalysisResponse result) {
    if (result.readings == null) {
      return "User scanned a test strip but no readings were found.";
    }

    final r = result.readings!;
    // Build a concise summary for the AI
    return """
[SYSTEM NOTIFICATION: User performed a urinalysis scan.]
RESULTS:
- Leukocytes: ${r.leukocytes?.value}
- Nitrites: ${r.nitrites?.value}
- Protein: ${r.protein?.value}
- pH: ${r.ph?.value}
- Blood: ${r.blood?.value}
- Glucose: ${r.glucose?.value}
- Ketones: ${r.ketones?.value}
- Billirubin: ${r.bilirubin?.value}

INSTRUCTION: Analyze these results. If any values are abnormal (Positive/High), explain what they might indicate in simple terms. Ask if they have specific symptoms related to these findings.
""";
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
