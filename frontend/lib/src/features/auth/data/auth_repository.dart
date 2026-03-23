import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'package:mediq_app/src/features/auth/data/user_model.dart';
import 'package:mediq_app/src/features/doctors/data/doctor_model.dart';

final authRepositoryProvider = Provider((ref) {
  return AuthRepository(ref.watch(dioProvider));
});

class AuthRepository {
  final Dio _dio;
  AuthRepository(this._dio);

  // --- AUTHENTICATION ---

  Future<void> login(String email, String password) async {
    try {
      final response = await _dio.post('/api/v1/auth/login', data: {
        'email': email,
        'password': password,
      });

      final token = response.data['access_token'];
      final refreshToken = response.data['refresh_token'];
      if (token != null) {
        final storage = FlutterSecureStorage();
        await storage.write(
          key: 'auth_token',
          value: token,
          aOptions: AndroidOptions(encryptedSharedPreferences: true),
        );
        if (refreshToken != null) {
          await storage.write(
            key: 'refresh_token',
            value: refreshToken,
            aOptions: AndroidOptions(encryptedSharedPreferences: true),
          );
        }
      }
    } on DioException catch (e) {
      final msg = e.response?.data['detail'] ?? "Login failed. Please check your connection.";
      throw Exception(msg);
    } catch (e) {
      throw Exception("Login failed: $e");
    }
  }

  Future<void> signup(String email, String password, String firstName, String lastName, DateTime dob) async {
    try {
      await _dio.post('/api/v1/auth/signup', data: {
        'email': email,
        'password': password,
        'first_name': firstName,
        'last_name': lastName,
        'dob': dob.toIso8601String().split('T')[0], // YYYY-MM-DD
        'role': 'patient'
      });
    } on DioException catch (e) {
      final msg = e.response?.data['detail'] ?? "Signup failed. Please try again.";
      throw Exception(msg);
    } catch (e) {
      throw Exception("Signup failed: $e");
    }
  }

  Future<void> logout() async {
    final storage = FlutterSecureStorage();
    await storage.delete(key: 'auth_token', aOptions: AndroidOptions(encryptedSharedPreferences: true));
    await storage.delete(key: 'refresh_token', aOptions: AndroidOptions(encryptedSharedPreferences: true));
  }

  // --- USER DATA ---

  Future<User?> getUserProfile() => getCurrentUser();

  Future<User?> getCurrentUser() async {
    try {
      final response = await _dio.get('/api/v1/auth/me');
      return User.fromJson(response.data);
    } catch (e) {
      return null;
    }
  }

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
    bool? settingsNotifications,
    bool? settingsEmailUpdates,
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

  Future<Doctor> getMyDoctorProfile() async {
    try {
      final response = await _dio.get('/api/v1/auth/my-doctor-profile');
      return Doctor.fromJson(response.data);
    } catch (e) {
      throw Exception("Failed to load doctor profile: $e");
    }
  }

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