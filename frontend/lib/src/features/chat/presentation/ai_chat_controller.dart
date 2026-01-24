import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';

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

  AiChatController(this._dio) : super(AiChatState());

  Future<void> sendMessage(String text, {String? imageUrl}) async {
    if (text.trim().isEmpty && imageUrl == null) return;

    final userMsg = {'role': 'user', 'message': text, 'image': imageUrl};
    state =
        state.copyWith(messages: [...state.messages, userMsg], isLoading: true);

    try {
      // Connects to your backend
      final response = await _dio.post('/api/v1/chat/analyze',
          data: {"message": text, "image_url": imageUrl});

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
final aiChatControllerProvider =
    StateNotifierProvider<AiChatController, AiChatState>((ref) {
  // Use the shared Dio Provider which has the Interceptors and Auth Token
  final dio = ref.watch(dioProvider); 
  return AiChatController(dio);
});
