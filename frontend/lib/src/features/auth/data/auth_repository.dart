import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:image_picker/image_picker.dart';
import 'package:http_parser/http_parser.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'package:mediq_app/src/features/auth/data/user_model.dart';
import 'package:mediq_app/src/features/doctors/data/doctor_model.dart';
import 'package:supabase_flutter/supabase_flutter.dart' as supabase;

final authRepositoryProvider = Provider((ref) {
  return AuthRepository(ref.watch(dioProvider));
});

class AuthRepository {
  final Dio _dio;
  AuthRepository(this._dio);

  static const _secureStorage = FlutterSecureStorage();
  static const _secureStorageOptions = AndroidOptions(
    encryptedSharedPreferences: true,
  );

  Future<void> _persistSession(supabase.Session? session) async {
    if (session == null) return;

    await _secureStorage.write(
      key: 'auth_token',
      value: session.accessToken,
      aOptions: _secureStorageOptions,
    );

    final refreshToken = session.refreshToken;
    if (refreshToken != null && refreshToken.isNotEmpty) {
      await _secureStorage.write(
        key: 'refresh_token',
        value: refreshToken,
        aOptions: _secureStorageOptions,
      );
    }
  }

  Future<void> _clearStoredSession() async {
    await _secureStorage.delete(
      key: 'auth_token',
      aOptions: _secureStorageOptions,
    );
    await _secureStorage.delete(
      key: 'refresh_token',
      aOptions: _secureStorageOptions,
    );
  }

  // --- AUTHENTICATION ---

  Future<void> login(String email, String password) async {
    try {
      final response = await supabase.Supabase.instance.client.auth.signInWithPassword(
        email: email,
        password: password,
      );
      await _persistSession(response.session);
    } on supabase.AuthException catch (e) {
      throw Exception(e.message);
    } catch (e) {
      throw Exception("Login failed: $e");
    }
  }

  Future<void> signup(String email, String password, String firstName, String lastName, DateTime dob) async {
    try {
      // 1. Authenticate / create user in Supabase
      final response = await supabase.Supabase.instance.client.auth.signUp(
        email: email,
        password: password,
      );
      await _persistSession(response.session);
      
      // 2. Provision the backend DB row
      if (response.user != null) {
        // At this point, Dio interceptor will pick up the Supabase session token
        // But since this is right after signup, we can just make the call.
        await _dio.post('/api/v1/auth/signup', data: {
          'email': email,
          'first_name': firstName,
          'last_name': lastName,
          'dob': dob.toIso8601String().split('T')[0], // YYYY-MM-DD
          'role': 'patient'
        });
      }
    } on supabase.AuthException catch (e) {
      throw Exception(e.message);
    } on DioException catch (e) {
      final msg = e.response?.data['detail'] ?? "Signup failed. Please try again.";
      throw Exception(msg);
    } catch (e) {
      throw Exception("Signup failed: $e");
    }
  }

  Future<void> logout() async {
    try {
      await supabase.Supabase.instance.client.auth.signOut();
    } catch (e) {
      debugPrint('Supabase logout error: $e');
    }

    await _clearStoredSession();
  }

  // --- USER DATA ---

  Future<User?> getUserProfile() async {
    if (supabase.Supabase.instance.client.auth.currentSession == null) {
      return null;
    }

    return getCurrentUser();
  }

  Future<User?> getCurrentUser() async {
    final response = await _dio.get('/api/v1/auth/me');
    return User.fromJson(response.data);
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

  Future<void> cancelSubscription() async {
    try {
      final response = await _dio.post('/api/v1/subscription/cancel-subscription');
      if (response.statusCode != null && response.statusCode! >= 400) {
        throw Exception("Failed to cancel subscription.");
      }
    } on DioException catch (e) {
      final msg = e.response?.data['detail'] ?? "Cancel subscription failed. Please try again.";
      throw Exception(msg);
    } catch (e) {
      throw Exception("Cancel subscription failed: $e");
    }
  }

  // --- SUPPORT ---

  Future<void> sendSupportMessage({required String subject, required String message}) async {
    try {
      await _dio.post('/api/v1/support/contact', data: {
        'subject': subject,
        'message': message,
      });
    } on DioException catch (e) {
      final msg = e.response?.data['detail'] ?? "Failed to send support message.";
      throw Exception(msg);
    } catch (e) {
      throw Exception("Support message failed: $e");
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
