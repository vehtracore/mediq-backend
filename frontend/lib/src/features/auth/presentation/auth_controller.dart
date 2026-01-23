import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';
import 'package:mediq_app/src/features/auth/data/auth_repository.dart';
import 'package:mediq_app/src/features/auth/presentation/user_controller.dart';
import 'package:mediq_app/src/features/chat/data/image_upload_service.dart';

final authControllerProvider = StateNotifierProvider<AuthController, AsyncValue<void>>((ref) {
  return AuthController(
    ref.read(authRepositoryProvider),
    ref.read(imageUploadServiceProvider),
    ref,
  );
});

class AuthController extends StateNotifier<AsyncValue<void>> {
  final AuthRepository _authRepository;
  final ImageUploadService _uploadService;
  final Ref _ref;

  AuthController(this._authRepository, this._uploadService, this._ref)
      : super(const AsyncData(null));

  Future<void> login(String email, String password) async {
    state = const AsyncLoading();
    state = await AsyncValue.guard(() => _authRepository.login(email, password));
    _ref.invalidate(userProvider);
  }

  Future<void> signUp(String email, String password, String firstName, String lastName) async {
    state = const AsyncLoading();
    state = await AsyncValue.guard(() => _authRepository.signup(email, password, firstName, lastName));
    _ref.invalidate(userProvider);
  }

  Future<void> logout() async {
    state = const AsyncLoading();
    await _authRepository.logout();
    state = const AsyncData(null);
    _ref.invalidate(userProvider);
  }

  // Fix: Added settings parameters here to match Repository
  Future<void> updateProfile({
    String? firstName,
    String? lastName,
    String? location,
    XFile? profileImage,
    String? bloodType,
    String? allergies,
    String? chronicConditions,
    String? medications,
    String? pastSurgeries,
    String? settingsTheme,
    bool? settingsNotifications, // <-- Added
    bool? settingsEmailUpdates,  // <-- Added
  }) async {
    state = const AsyncLoading();

    try {
      String? imageUrl;
      if (profileImage != null) {
        imageUrl = await _uploadService.uploadFile(profileImage); 
      }

      await _authRepository.updateUser(
        firstName: firstName,
        lastName: lastName,
        location: location,
        imageUrl: imageUrl,
        bloodType: bloodType,
        allergies: allergies,
        chronicConditions: chronicConditions,
        medications: medications,
        pastSurgeries: pastSurgeries,
        settingsTheme: settingsTheme,
        settingsNotifications: settingsNotifications, // <-- Passed to Repo
        settingsEmailUpdates: settingsEmailUpdates,   // <-- Passed to Repo
      );

      _ref.invalidate(userProvider);
      state = const AsyncData(null);
    } catch (e, stack) {
      state = AsyncError(e, stack);
      rethrow;
    }
  }
}