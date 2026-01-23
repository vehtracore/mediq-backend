import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'package:mediq_app/src/features/auth/data/user_model.dart';

final authRepositoryProvider = Provider((ref) {
  return AuthRepository(ref.watch(dioProvider));
});

class AuthRepository {
  final Dio _dio;
  AuthRepository(this._dio);

  // --- AUTHENTICATION ---
  
  Future<void> login(String email, String password) async {
    try {
      // Note: FastAPI OAuth2FormRequest usually expects 'username', not 'email'
      await _dio.post('/api/v1/auth/login', data: {
        'username': email, 
        'password': password,
      });
    } catch (e) {
      throw Exception("Login failed: $e");
    }
  }

  Future<void> signup(String email, String password, String firstName, String lastName) async {
    try {
      await _dio.post('/api/v1/auth/signup', data: {
        'email': email,
        'password': password,
        'first_name': firstName,
        'last_name': lastName,
        'role': 'patient'
      });
    } catch (e) {
      throw Exception("Signup failed: $e");
    }
  }

  Future<void> logout() async {
    // Clear tokens logic would go here if managing local storage manually
  }

  // --- USER DATA ---

  // Fix 1: Alias for getCurrentUser so user_controller works
  Future<User?> getUserProfile() => getCurrentUser();

  Future<User?> getCurrentUser() async {
    try {
      final response = await _dio.get('/api/v1/auth/me');
      return User.fromJson(response.data);
    } catch (e) {
      return null;
    }
  }

  // Fix 2: Added ALL missing parameters including settings
  Future<void> updateUser({
    String? firstName,
    String? lastName,
    String? location,
    String? imageUrl,
    String? bloodType,
    String? allergies,
    String? chronicConditions,
    String? medications,
    String? pastSurgeries,
    String? settingsTheme,
    bool? settingsNotifications, // <-- ADDED
    bool? settingsEmailUpdates,  // <-- ADDED
  }) async {
    try {
      final Map<String, dynamic> data = {};
      
      if (firstName != null) data['first_name'] = firstName;
      if (lastName != null) data['last_name'] = lastName;
      if (location != null) data['location'] = location;
      if (imageUrl != null) data['image_url'] = imageUrl;
      
      if (bloodType != null) data['blood_type'] = bloodType;
      if (allergies != null) data['allergies'] = allergies;
      if (chronicConditions != null) data['chronic_conditions'] = chronicConditions;
      if (medications != null) data['medications'] = medications;
      if (pastSurgeries != null) data['past_surgeries'] = pastSurgeries;
      
      if (settingsTheme != null) data['settings_theme'] = settingsTheme;
      if (settingsNotifications != null) data['settings_notifications'] = settingsNotifications;
      if (settingsEmailUpdates != null) data['settings_email_updates'] = settingsEmailUpdates;

      await _dio.put('/api/v1/auth/me', data: data);
    } catch (e) {
      throw Exception("Update failed: $e");
    }
  }

  // --- DOCTOR FEATURES ---

  Future<dynamic> getMyDoctorProfile() async {
    try {
      final response = await _dio.get('/api/v1/auth/my-doctor-profile');
      return response.data; 
    } catch (e) {
      throw Exception("Failed to load doctor profile");
    }
  }

  // Fix 3: Ensures registerDoctor accepts the Map data
  Future<void> registerDoctor(Map<String, dynamic> data) async {
    try {
      await _dio.post('/api/v1/auth/doctor/register', data: data);
    } catch (e) {
      throw Exception("Doctor registration failed: $e");
    }
  }

  // --- SUBSCRIPTION ---

  Future<void> upgradeToPremium() async {
    try {
      await _dio.post('/api/v1/subscription/upgrade');
    } catch (e) {
      throw Exception("Upgrade failed: $e");
    }
  }
}