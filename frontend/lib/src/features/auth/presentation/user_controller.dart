import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/features/auth/data/auth_repository.dart';
import 'package:mediq_app/src/features/auth/data/auth_state_provider.dart';
import 'package:mediq_app/src/features/auth/data/shell_identity.dart';
import 'package:mediq_app/src/features/auth/data/user_model.dart';

final userProvider = FutureProvider<User?>((ref) async {
  final repo = ref.watch(authRepositoryProvider);
  final userId = ref.watch(authUserIdProvider);
  if (userId == null) return null;

  final User? remote = await repo.getUserProfile();
  if (remote != null) {
    await ref
        .read(shellIdentityStoreProvider)
        .write(ShellIdentity.fromUser(userId, remote));
    ref.invalidate(activeShellIdentityProvider);
  }
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
