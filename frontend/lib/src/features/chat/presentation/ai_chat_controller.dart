import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'package:mediq_app/src/features/auth/presentation/user_controller.dart';

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
  final String subscriptionTier; // "free" or "premium"

  AiChatController(this._dio, this.subscriptionTier) : super(AiChatState());

  Future<void> sendMessage(String text, {String? imageUrl}) async {
    if (text.trim().isEmpty && imageUrl == null) return;

    final userMsg = {'role': 'user', 'message': text, 'image': imageUrl};
    state =
        state.copyWith(messages: [...state.messages, userMsg], isLoading: true);

    try {
      // --- PREPARE HISTORY (Premium Only) ---
      List<Map<String, dynamic>> history = [];
      
      if (subscriptionTier == 'premium') {
        // Convert local chat state to Gemini History Format
        // Exclude the very last message we just added (that's the current query)
        // And exclude any system/error messages
        
        for (var msg in state.messages) {
             if (msg == userMsg) continue; // Skip current
             if (msg['role'] == 'system') continue; // Skip errors

             // Map roles: 'user'->'user', 'ai'->'model'
             String role = (msg['role'] == 'user') ? 'user' : 'model';
             
             // Gemini expects: {'role': '...', 'parts': ['...']}
             // Note: We are only sending text history for now to keep it simple/cheap
             history.add({
               'role': role, 
               'parts': [ msg['message'] ] 
             });
        }
      }

      // Connects to your backend
      final response = await _dio.post('/api/v1/chat/analyze',
          data: {
            "message": text, 
            "image_url": imageUrl,
            "history": history // Send history (empty if free)
          });

      final aiMsg = {'role': 'ai', 'message': response.data['response']};
      state = state
          .copyWith(messages: [...state.messages, aiMsg], isLoading: false);
    } on DioException catch (e) {
      String errorMessage = "Connection error. Please try again.";
      
      // Extract specific error from backend (e.g. Free Tier Limit)
      if (e.response != null && e.response?.data != null) {
         final data = e.response?.data;
         if (data is Map && data.containsKey('detail')) {
           errorMessage = data['detail'];
         }
      }

      final errorMsg = {
        'role': 'system',
        'message': errorMessage
      };
      state = state.copyWith(messages: [...state.messages, errorMsg], isLoading: false);
    } catch (e) {
      final errorMsg = {
        'role': 'system',
        'message': "System Error: ${e.toString()}"
      };
      state = state.copyWith(messages: [...state.messages, errorMsg], isLoading: false);
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
