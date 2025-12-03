import 'dart:async';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/features/auth/data/auth_repository.dart';
import 'package:mediq_app/src/core/storage/storage_service.dart';
import 'package:mediq_app/src/features/auth/presentation/user_controller.dart';

final authControllerProvider = AsyncNotifierProvider<AuthController, void>(() {
  return AuthController();
});

class AuthController extends AsyncNotifier<void> {
  @override
  FutureOr<void> build() {
    return null;
  }

  Future<void> signUp({
    required String firstName,
    required String lastName,
    required String location,
    required DateTime dob,
    required String email,
    required String password,
  }) async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(() async {
      final authRepository = ref.read(authRepositoryProvider);
      final storageService = ref.read(storageServiceProvider);

      await authRepository.signUp(
        firstName: firstName,
        lastName: lastName,
        location: location,
        dob: dob,
        email: email,
        password: password,
      );

      final token = await authRepository.login(
        email: email,
        password: password,
      );

      await storageService.saveToken(token);
    });
  }

  Future<void> login({required String email, required String password}) async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(() async {
      final authRepository = ref.read(authRepositoryProvider);
      final storageService = ref.read(storageServiceProvider);

      final token = await authRepository.login(
        email: email,
        password: password,
      );

      await storageService.saveToken(token);
    });
  }

  Future<void> logout() async {
    final storageService = ref.read(storageServiceProvider);
    await storageService.deleteToken();
    state = const AsyncValue.data(null);
  }

  Future<void> updateProfile({
    required String firstName,
    required String lastName,
    required String location,
  }) async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(() async {
      final authRepository = ref.read(authRepositoryProvider);

      await authRepository.updateProfile(
        firstName: firstName,
        lastName: lastName,
        location: location,
      );

      ref.invalidate(userProvider);
    });
  }

  // --- FIXED METHOD ---
  Future<void> registerDoctor({
    required String fullName,
    required String email,
    required String password,
    required String specialty,
    required String licenseNumber,
  }) async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(() async {
      // FIX: Using ref.read to get the repository
      final authRepository = ref.read(authRepositoryProvider);

      await authRepository.registerDoctor(
        fullName: fullName,
        email: email,
        password: password,
        specialty: specialty,
        licenseNumber: licenseNumber,
      );
    });
  }
}
