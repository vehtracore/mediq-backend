import 'dart:async';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/features/chat/data/chat_repository.dart';
import 'package:mediq_app/src/core/api/app_exception.dart';

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

      final failure = e is AppException ? e.failure : null;
      if (failure?.code == 'quota_exceeded' ||
          failure?.code == 'cooldown_active' ||
          failure?.code == 'rate_limited') {
        throw Exception("LIMIT_REACHED");
      }
      rethrow;
    }
  }
}
