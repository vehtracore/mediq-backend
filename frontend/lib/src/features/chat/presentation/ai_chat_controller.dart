import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

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
    } catch (e) {
      final errorMsg = {
        'role': 'system',
        'message': "Connection error. Please try again."
      };
      state = state
          .copyWith(messages: [...state.messages, errorMsg], isLoading: false);
    }
  }
}

// 3. PROVIDER
final aiChatControllerProvider =
    StateNotifierProvider<AiChatController, AiChatState>((ref) {
  // Standalone Dio Client
  final dio = Dio(BaseOptions(
    baseUrl: 'https://mediq-backend-m3ik.onrender.com',
    connectTimeout: const Duration(seconds: 20),
    receiveTimeout: const Duration(seconds: 20),
    headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
  ));

  return AiChatController(dio);
});
