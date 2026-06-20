import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'package:mediq_app/src/features/auth/presentation/user_controller.dart';
import 'package:mediq_app/src/features/lab/data/lab_result_model.dart';

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
  String? _conversationMemory;
  final List<String> _unsummarizedTurns = [];
  int _requestSequence = 0;

  AiChatController(this._dio, this.subscriptionTier) : super(AiChatState());

  Future<bool> hasActiveConsent() async {
    final response = await _dio.get('/api/v1/ai/consent/status');
    return response.data['consent_granted'] == true;
  }

  Future<bool> grantConsent() async {
    final response = await _dio.post('/api/v1/ai/consent');
    return response.data['consent_granted'] == true;
  }

  List<Map<String, dynamic>> _recentGeminiHistory({String? excludeId}) {
    final eligible = state.messages.where((message) {
      if (message['role'] == 'system') return false;
      if (excludeId != null && message['id'] == excludeId) return false;
      return message['role'] == 'user' || message['role'] == 'ai';
    }).toList();

    final recent = eligible.length > 10
        ? eligible.sublist(eligible.length - 10)
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

  String _nextRequestId() {
    _requestSequence += 1;
    return 'ai-${DateTime.now().microsecondsSinceEpoch}-$_requestSequence';
  }

  Future<void> sendMessage(String text,
      {String? imageUrl,
      String? imagePublicId,
      String language = 'English'}) async {
    if (state.isLoading) return;
    if (text.trim().isEmpty && imageUrl == null) return;

    final tempId = DateTime.now().millisecondsSinceEpoch.toString();
    final requestId = _nextRequestId();
    final userMsg = {
      'id': tempId,
      'role': 'user',
      'message': text,
      'image': imageUrl,
      'isSending': true
    };
    state =
        state.copyWith(messages: [...state.messages, userMsg], isLoading: true);

    try {
      // --- PREPARE HISTORY (Premium Only) ---
      final hasSessionMemory = {'premium', 'family'}.contains(subscriptionTier);
      final history = hasSessionMemory
          ? _recentGeminiHistory(excludeId: tempId)
          : <Map<String, dynamic>>[];
      final shouldUpdateMemory =
          hasSessionMemory && _unsummarizedTurns.length >= 7;
      final olderTurnsLeavingWindow =
          shouldUpdateMemory ? _olderUnsummarizedTurns() : null;

      // Connects to your backend
      final response = await _dio.post('/api/v1/chat/analyze',
          data: {
            "message": text,
            "image_url": imageUrl,
            "image_public_id": imagePublicId,
            "history": history, // Send history (empty if free)
            "language": language, // Send selected language
            "conversation_memory": _conversationMemory,
            "memory_source": olderTurnsLeavingWindow,
            "update_memory": shouldUpdateMemory,
          },
          options: Options(headers: {'X-AI-Request-ID': requestId}));

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
          'User: $text\nAssistant: ${response.data['response']}',
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

      // Extract specific error from backend (e.g. Free Tier Limit)
      if (e.response != null && e.response?.data != null) {
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
      debugPrint('[AiChatController] sendMessage error: $e');
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

  Future<void> sendLabResult(LabAnalysisResponse result) async {
    if (state.isLoading) return;

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
            "history": _recentGeminiHistory(),
            "conversation_memory": _conversationMemory,
            "memory_source": _olderUnsummarizedTurns(),
            "update_memory": false,
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

  /// Generates an AI summary of the session and saves it to the Health Vault.
  /// Returns [true] if the save was successful, [false] otherwise.
  Future<bool> saveSummary() async {
    if (!mounted) return false;
    if (state.isLoading) return false;
    state = state.copyWith(isLoading: true);

    try {
      // 1. Ask the AI to produce a structured medical summary
      final response = await _dio.post('/api/v1/chat/analyze',
          data: {
            "message":
                "Summarize this entire conversation into a structured medical note. "
                    "Sections: 1. Patient Symptoms, 2. Lab Results (if any), "
                    "3. Recommended Actions. Keep it professional.",
            "history": _recentGeminiHistory(),
            "conversation_memory": _conversationMemory,
            "memory_source": _olderUnsummarizedTurns(),
            "update_memory": false,
          },
          options: Options(headers: {'X-AI-Request-ID': _nextRequestId()}));

      final summaryText = response.data['response'] as String;

      // 2. POST to Health Vault
      await _dio.post('/api/v1/vault/ai-summary', data: {
        "topic": "AI Symptom Analysis",
        "summary_text": summaryText,
      });

      if (!mounted) return false;
      state = state.copyWith(isLoading: false);
      return true;
    } catch (e) {
      debugPrint("[AiChatController] saveSummary error: $e");
      if (!mounted) return false;
      state = state.copyWith(isLoading: false);
      return false;
    }
  }
}

// 3. PROVIDER
// autoDispose ensures the session is wiped when user leaves the screen
final aiChatControllerProvider =
    StateNotifierProvider.autoDispose<AiChatController, AiChatState>((ref) {
  final dio = ref.watch(dioProvider);

  // Get User Tier (default to 'free' if loading)
  final userAsync = ref.watch(userProvider);
  final tier = userAsync.value?.subscriptionTier ?? 'free';

  return AiChatController(dio, tier);
});
