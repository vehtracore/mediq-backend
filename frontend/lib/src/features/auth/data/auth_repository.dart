import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:image_picker/image_picker.dart';
import 'package:http_parser/http_parser.dart';
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
        const storage = FlutterSecureStorage();
        await storage.write(
          key: 'auth_token',
          value: token,
          aOptions: const AndroidOptions(encryptedSharedPreferences: true),
        );
        if (refreshToken != null) {
          await storage.write(
            key: 'refresh_token',
            value: refreshToken,
            aOptions: const AndroidOptions(encryptedSharedPreferences: true),
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
    const storage = FlutterSecureStorage();
    await storage.delete(key: 'auth_token', aOptions: const AndroidOptions(encryptedSharedPreferences: true));
    await storage.delete(key: 'refresh_token', aOptions: const AndroidOptions(encryptedSharedPreferences: true));
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
    // Emergency / NOK fields
    String? kinPhone,
    bool? emergencySmsEnabled,
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

      // Emergency / NOK fields
      if (kinPhone != null) data['kin_phone'] = kinPhone;
      if (emergencySmsEnabled != null) data['emergency_sms_enabled'] = emergencySmsEnabled;

      await _dio.put('/api/v1/auth/me', data: data);
    } catch (e) {
      throw Exception("Update failed: $e");
    }
  }

  Future<void> updateDeviceToken(String fcmToken) async {
    try {
      await _dio.patch('/api/v1/auth/me/device-token', data: {
        'fcm_token': fcmToken,
      });
    } catch (e) {
      debugPrint("Failed to sync FCM token: $e");
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

  /// Submits corrected documents for a rejected doctor.
  /// Returns the updated Doctor profile (status will be 'pending').
  Future<Doctor> reapply({
    String? licenseNumber,
    String? mdcnLicenseUrl,
    String? indemnityCertUrl,
  }) async {
    try {
      final Map<String, dynamic> data = {};
      if (licenseNumber != null) data['license_number'] = licenseNumber;
      if (mdcnLicenseUrl != null) data['mdcn_license_url'] = mdcnLicenseUrl;
      if (indemnityCertUrl != null) data['indemnity_cert_url'] = indemnityCertUrl;

      final response = await _dio.post('/api/v1/doctors/me/reapply', data: data);
      return Doctor.fromJson(response.data);
    } on DioException catch (e) {
      final msg = e.response?.data['detail'] ?? "Reapply failed. Please try again.";
      throw Exception(msg);
    } catch (e) {
      throw Exception("Reapply failed: $e");
    }
  }

  Future<void> registerDoctor({
    required String fullName,
    required String email,
    required String password,
    required String specialty,
    required String licenseNumber,
    required XFile mdcnLicense,
    required XFile indemnityCertificate,
  }) async {
    try {
      final Map<String, dynamic> mapData = {
        'full_name': fullName,
        'email': email,
        'password': password,
        'specialty': specialty,
        'license_number': licenseNumber,
      };

      if (kIsWeb) {
        mapData['mdcn_license'] = MultipartFile.fromBytes(
          await mdcnLicense.readAsBytes(),
          filename: mdcnLicense.name.isEmpty ? 'license.jpg' : mdcnLicense.name,
          contentType: MediaType('image', 'jpeg'),
        );
        mapData['indemnity_certificate'] = MultipartFile.fromBytes(
          await indemnityCertificate.readAsBytes(),
          filename: indemnityCertificate.name.isEmpty ? 'indemnity.jpg' : indemnityCertificate.name,
          contentType: MediaType('image', 'jpeg'),
        );
      } else {
        mapData['mdcn_license'] = await MultipartFile.fromFile(
          mdcnLicense.path,
          filename: mdcnLicense.name.isEmpty ? 'license.jpg' : mdcnLicense.name,
          contentType: MediaType('image', 'jpeg'),
        );
        mapData['indemnity_certificate'] = await MultipartFile.fromFile(
          indemnityCertificate.path,
          filename: indemnityCertificate.name.isEmpty ? 'indemnity.jpg' : indemnityCertificate.name,
          contentType: MediaType('image', 'jpeg'),
        );
      }

      final formData = FormData.fromMap(mapData);
      await _dio.post('/api/v1/auth/doctor/register', data: formData);
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

  // --- FAMILY PLAN ---

  Future<String> generateFamilyInvite() async {
    try {
      final response = await _dio.get('/api/v1/family/invite-code');
      return response.data['invite_code'];
    } on DioException catch (e) {
      final msg = e.response?.data['detail'] ?? "Failed to generate invite.";
      throw Exception(msg);
    } catch (e) {
      throw Exception("Generate invite failed: \$e");
    }
  }

  Future<void> joinFamily(String inviteCode) async {
    try {
      await _dio.post('/api/v1/family/join', data: {
        'invite_code': inviteCode,
      });
    } on DioException catch (e) {
      final msg = e.response?.data['detail'] ?? "Failed to join family plan.";
      throw Exception(msg);
    } catch (e) {
      throw Exception("Join family failed: \$e");
    }
  }
}