import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http_parser/http_parser.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
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
  final String subscriptionTier; // "free", "premium", or "family"
  final AiChatContinuation? continuation;
  String? _conversationMemory;
  final List<String> _unsummarizedTurns = [];
  int _requestSequence = 0;
  String? _pendingSaveRequestId;

  AiChatController(this._dio, this.subscriptionTier, this.continuation)
      : super(AiChatState());

  String? get sourceSummaryId => continuation?.summaryId;
  bool get hasPaidContinuity =>
      {'premium', 'family'}.contains(subscriptionTier);

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
      String errorMessage = "Connection error. Please try again.";

      // PDF/provider failures get a stable message. Quota and ownership
      // responses remain actionable without exposing implementation details.
      if (document != null) {
        final status = e.response?.statusCode;
        if (status == 413) {
          errorMessage = 'PDFs must be 8 MB or smaller.';
        } else if (status == 429) {
          final data = e.response?.data;
          errorMessage = data is Map && data['detail'] is String
              ? data['detail'] as String
              : 'Your AI attachment limit has been reached.';
        } else if (status == 404 && sourceSummaryId != null) {
          errorMessage = 'This saved conversation is no longer available.';
        } else {
          errorMessage =
              'This PDF could not be processed. Please choose a valid PDF and try again.';
        }
      } else if (e.response != null && e.response?.data != null) {
        final data = e.response?.data;
        if (data is Map && data.containsKey('detail')) {
          errorMessage = data['detail'];
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
    } catch (e) {
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
    } catch (e) {
      debugPrint('[AiChatController] temporary image cleanup failed: $e');
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
    } catch (e) {
      debugPrint('[AiChatController] sendLabResult error: $e');
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
    } catch (e) {
      debugPrint('[AiChatController] summary save failed.');
      if (!mounted) return false;
      state = state.copyWith(isLoading: false);
      return false;
    }
  }
}

// 3. PROVIDER
// autoDispose ensures the session is wiped when user leaves the screen
final aiChatControllerProvider = StateNotifierProvider.autoDispose
    .family<AiChatController, AiChatState, AiChatContinuation?>(
        (ref, continuation) {
  final dio = ref.watch(dioProvider);

  // Get User Tier (default to 'free' if loading)
  final userAsync = ref.watch(userProvider);
  final tier = userAsync.value?.subscriptionTier ?? 'free';

  return AiChatController(dio, tier, continuation);
});
