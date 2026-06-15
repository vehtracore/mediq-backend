import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/features/auth/data/auth_repository.dart';
import 'package:mediq_app/src/features/auth/data/user_model.dart';
import 'package:supabase_flutter/supabase_flutter.dart' hide User;

final userProvider = FutureProvider<User?>((ref) async {
  final repo = ref.watch(authRepositoryProvider);

  if (Supabase.instance.client.auth.currentSession == null) {
    return null;
  }

  final User? remote = await repo.getUserProfile();
  return remote;
});

class UserController extends StateNotifier<AsyncValue<User?>> {
  UserController() : super(const AsyncValue.data(null));

  void setUser(User user) {
    state = AsyncValue.data(user);
  }

  void logout() {
    state = const AsyncValue.data(null);
  }
}

final userControllerProvider =
    StateNotifierProvider<UserController, AsyncValue<User?>>((ref) {
  return UserController();
});
