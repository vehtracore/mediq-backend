import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/features/auth/data/auth_repository.dart';

// Provides the current user state asynchronously
final userProvider = FutureProvider<User>((ref) async {
  final repo = ref.watch(authRepositoryProvider);
  return await repo.getUserProfile();
});
