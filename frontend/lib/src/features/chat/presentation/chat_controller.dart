import 'dart:async';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/features/chat/data/chat_repository.dart';

final chatControllerProvider = AsyncNotifierProvider<ChatController, void>(() {
  return ChatController();
});

class ChatController extends AsyncNotifier<void> {
  @override
  FutureOr<void> build() {
    return null;
  }

  Future<String> sendMessage(String text) async {
    state = const AsyncLoading();
    try {
      final repo = ref.read(chatRepositoryProvider);
      final response = await repo.sendMessage(text);
      state = const AsyncData(null);
      return response;
    } catch (e, st) {
      state = AsyncError(e, st);

      // CHECK FOR LIMIT ERROR FROM BACKEND
      // The backend sends "Free tier limit reached" or "You are chatting too fast"
      final errorString = e.toString();
      if (errorString.contains("Free tier limit") ||
          errorString.contains("chatting too fast")) {
        throw Exception("LIMIT_REACHED");
      }
      rethrow;
    }
  }
}
