import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/features/auth/data/auth_repository.dart';
import 'package:mediq_app/src/features/auth/data/user_model.dart';

final userProvider = FutureProvider<User?>((ref) async {
  final repo = ref.watch(authRepositoryProvider);

  try {
    // This fetches the clean User object directly from the repo
    final User remote = await repo.getUserProfile();
    return remote;
  } catch (e) {
    // If user is not logged in or error occurs, return null
    return null;
  }
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
