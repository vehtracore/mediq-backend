import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';
import 'package:mediq_app/src/features/auth/data/auth_repository.dart';
import 'package:mediq_app/src/features/auth/presentation/user_controller.dart';
import 'package:mediq_app/src/features/chat/data/image_upload_service.dart';
import 'package:mediq_app/src/core/services/notification_service.dart';

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
    
    if (!state.hasError) {
      _syncDeviceToken();
    }
    
    _ref.invalidate(userProvider);
  }

  Future<void> _syncDeviceToken() async {
    final notificationService = _ref.read(notificationServiceProvider);
    final token = await notificationService.getToken();
    if (token != null) {
      await _authRepository.updateDeviceToken(token);
    }
  }

  Future<void> signUp(String email, String password, String firstName, String lastName, DateTime dob) async {
    state = const AsyncLoading();
    
    // signUp() creates an authenticated Supabase session automatically.
    // The GoRouter redirect listens to onAuthStateChange and will navigate
    // to the appropriate dashboard once the session is established.
    state = await AsyncValue.guard(
      () => _authRepository.signup(email, password, firstName, lastName, dob),
    );

    if (!state.hasError) {
      _syncDeviceToken();
      _ref.invalidate(userProvider);
    }
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
    bool? settingsNotifications,
    bool? settingsEmailUpdates,
    // Emergency / NOK fields
    String? kinPhone,
    bool? emergencySmsEnabled,
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
        settingsNotifications: settingsNotifications,
        settingsEmailUpdates: settingsEmailUpdates,
        kinPhone: kinPhone,
        emergencySmsEnabled: emergencySmsEnabled,
      );

      _ref.invalidate(userProvider);
      state = const AsyncData(null);
    } catch (e, stack) {
      state = AsyncError(e, stack);
      rethrow;
    }
  }
}