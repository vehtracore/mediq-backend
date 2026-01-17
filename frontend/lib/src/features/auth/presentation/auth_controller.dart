import 'dart:async';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart'; // ✅ Use XFile
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
      final user = await authRepository.getUserProfile();
      ref.read(userControllerProvider.notifier).setUser(user);
    });
  }

  Future<void> logout() async {
    final storageService = ref.read(storageServiceProvider);
    await storageService.deleteToken();
    ref.read(userControllerProvider.notifier).logout();
    state = const AsyncValue.data(null);
  }

  // --- 🚀 UPDATE PROFILE (Accepts XFile) ---
  Future<void> updateProfile({
    String? firstName,
    String? lastName,
    String? location,
    XFile? profileImage, // ✅ Changed to XFile (matches UI and Repo)
    String? bloodType,
    String? allergies,
    String? chronicConditions,
    String? medications,
    String? pastSurgeries,
    String? settingsTheme,
    bool? settingsNotifications,
    bool? settingsEmailUpdates,
  }) async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(() async {
      final authRepository = ref.read(authRepositoryProvider);

      final Map<String, dynamic> data = {};
      if (firstName != null) data['first_name'] = firstName;
      if (lastName != null) data['last_name'] = lastName;
      if (location != null) data['location'] = location;

      if (bloodType != null) data['blood_type'] = bloodType;
      if (allergies != null) data['allergies'] = allergies;
      if (chronicConditions != null)
        data['chronic_conditions'] = chronicConditions;
      if (medications != null) data['medications'] = medications;
      if (pastSurgeries != null) data['past_surgeries'] = pastSurgeries;

      if (settingsTheme != null) data['settings_theme'] = settingsTheme;
      if (settingsNotifications != null)
        data['settings_notifications'] = settingsNotifications;
      if (settingsEmailUpdates != null)
        data['settings_email_updates'] = settingsEmailUpdates;

      // Send XFile to Repository
      final updatedUser =
          await authRepository.updateProfile(data, profileImage: profileImage);

      ref.read(userControllerProvider.notifier).setUser(updatedUser);
    });
  }

  Future<void> registerDoctor({
    required String fullName,
    required String email,
    required String password,
    required String specialty,
    required String licenseNumber,
  }) async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(() async {
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
