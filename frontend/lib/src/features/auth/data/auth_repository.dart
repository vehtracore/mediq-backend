import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:image_picker/image_picker.dart';
import 'package:http_parser/http_parser.dart';
import 'package:mediq_app/src/core/api/app_exception.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'package:mediq_app/src/core/utils/ui_error_formatter.dart';
import 'package:mediq_app/src/features/auth/data/user_model.dart';
import 'package:mediq_app/src/features/auth/data/profile_exception.dart';
import 'package:mediq_app/src/features/doctors/data/doctor_model.dart';
import 'package:supabase_flutter/supabase_flutter.dart' as supabase;

final authRepositoryProvider = Provider((ref) {
  return AuthRepository(ref.watch(dioProvider));
});

class SupportSubmissionResult {
  const SupportSubmissionResult({
    required this.requestId,
    required this.status,
  });

  final String requestId;
  final String status;

  bool get isSent => status == 'sent';
}

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
      final response =
          await supabase.Supabase.instance.client.auth.signInWithPassword(
        email: email,
        password: password,
      );
      await _persistSession(response.session);
    } on supabase.AuthException catch (e) {
      throw AppException(e.message, originalException: e);
    } catch (error) {
      throw AppException(
        UIErrorFormatter.getMessage(error),
        originalException: error,
      );
    }
  }

  Future<void> signup(String email, String password, String firstName,
      String lastName, DateTime dob) async {
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
      throw AppException(e.message, originalException: e);
    } catch (e) {
      throw AppException(
        UIErrorFormatter.getMessage(e),
        originalException: e,
      );
    }
  }

  Future<void> logout() async {
    try {
      await supabase.Supabase.instance.client.auth.signOut();
    } catch (e) {
      debugPrint('[AUTH] Supabase logout reported an error.');
    }

    await _clearStoredSession();
  }

  Future<void> clearRedundantSessionCopiesAfterLogout() =>
      _clearStoredSession();

  // --- USER DATA ---

  Future<User?> getUserProfile() async {
    if (supabase.Supabase.instance.client.auth.currentSession == null) {
      return null;
    }

    return getCurrentUser();
  }

  Future<User> getCurrentUser() async {
    try {
      final response = await _dio.get('/api/v1/auth/me');
      final data = response.data;
      if (data is! Map<String, dynamic>) {
        throw const FormatException('Profile response is not an object.');
      }

      final user = User.fromJson(data);
      final displayName = '${user.firstName} ${user.lastName}'.trim();
      const validRoles = {'patient', 'doctor', 'admin'};
      final rawRole = data['role'];
      if (user.id.isEmpty ||
          displayName.isEmpty ||
          user.firstName.trim().isEmpty ||
          user.lastName.trim().isEmpty ||
          rawRole is! String ||
          !validRoles.contains(rawRole) ||
          !validRoles.contains(user.role)) {
        throw const ProfileAuthoritativeException(
          'Your MDQ+ profile is incomplete or invalid.',
        );
      }
      if (kDebugMode) debugPrint('[PROFILE] load succeeded');
      return user;
    } on ProfileAuthoritativeException {
      if (kDebugMode) debugPrint('[PROFILE] authoritative load failure');
      rethrow;
    } on DioException catch (error) {
      final statusCode = error.response?.statusCode;
      if (statusCode == 401 || statusCode == 403 || statusCode == 404) {
        if (kDebugMode) debugPrint('[PROFILE] authoritative load failure');
        throw ProfileAuthoritativeException(
          'Your account profile could not be verified. Please try again.',
          cause: error,
        );
      }

      if (kDebugMode) debugPrint('[PROFILE] temporary load failure');
      throw ProfileTemporaryException(
        statusCode != null && statusCode >= 500
            ? 'Your profile is temporarily unavailable. Please try again.'
            : 'Check your connection and try loading your profile again.',
        cause: error,
      );
    } on FormatException catch (error) {
      if (kDebugMode) debugPrint('[PROFILE] invalid profile response');
      throw ProfileTemporaryException(
        'Your profile could not be displayed yet. Please try again.',
        cause: error,
      );
    } catch (error) {
      if (kDebugMode) debugPrint('[PROFILE] temporary load failure');
      throw ProfileTemporaryException(
        'Your profile is temporarily unavailable. Please try again.',
        cause: error,
      );
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
      if (chronicConditions != null)
        data['chronic_conditions'] = chronicConditions;
      if (medications != null) data['medications'] = medications;
      if (pastSurgeries != null) data['past_surgeries'] = pastSurgeries;

      if (settingsTheme != null) data['settings_theme'] = settingsTheme;
      if (settingsNotifications != null)
        data['settings_notifications'] = settingsNotifications;
      if (settingsEmailUpdates != null)
        data['settings_email_updates'] = settingsEmailUpdates;

      // Emergency / NOK fields
      if (kinPhone != null) data['kin_phone'] = kinPhone;
      if (emergencySmsEnabled != null)
        data['emergency_sms_enabled'] = emergencySmsEnabled;

      await _dio.put('/api/v1/auth/me', data: data);
    } catch (e) {
      throw AppException(
        UIErrorFormatter.getMessage(e),
        originalException: e,
      );
    }
  }

  Future<void> registerDeviceToken({
    required String fcmToken,
    required String installationId,
    required String platform,
  }) async {
    await _dio.put('/api/v1/auth/me/device-token', data: {
      'fcm_token': fcmToken,
      'installation_id': installationId,
      'platform': platform,
    });
  }

  Future<void> unregisterDeviceToken({
    required String installationId,
  }) async {
    await _dio.delete('/api/v1/auth/me/device-token', data: {
      'installation_id': installationId,
    });
  }

  // --- DOCTOR FEATURES ---

  Future<Doctor> getMyDoctorProfile() async {
    try {
      final response = await _dio.get('/api/v1/auth/my-doctor-profile');
      return Doctor.fromJson(response.data);
    } catch (e) {
      throw AppException(
        UIErrorFormatter.getMessage(e),
        originalException: e,
      );
    }
  }

  /// Submits corrected documents for a rejected doctor.
  /// Returns the updated Doctor profile (status will be 'pending').
  Future<void> reapply({
    String? licenseNumber,
    required XFile mdcnLicense,
    required XFile indemnityCertificate,
  }) async {
    try {
      final Map<String, dynamic> data = {};
      if (licenseNumber != null) data['license_number'] = licenseNumber;
      if (kIsWeb) {
        data['mdcn_license'] = MultipartFile.fromBytes(
          await mdcnLicense.readAsBytes(),
          filename: mdcnLicense.name.isEmpty ? 'license.jpg' : mdcnLicense.name,
        );
        data['indemnity_certificate'] = MultipartFile.fromBytes(
          await indemnityCertificate.readAsBytes(),
          filename: indemnityCertificate.name.isEmpty
              ? 'indemnity.jpg'
              : indemnityCertificate.name,
        );
      } else {
        data['mdcn_license'] = await MultipartFile.fromFile(
          mdcnLicense.path,
          filename: mdcnLicense.name.isEmpty ? 'license.jpg' : mdcnLicense.name,
        );
        data['indemnity_certificate'] = await MultipartFile.fromFile(
          indemnityCertificate.path,
          filename: indemnityCertificate.name.isEmpty
              ? 'indemnity.jpg'
              : indemnityCertificate.name,
        );
      }
      await _dio.post(
        '/api/v1/doctors/me/verification-submissions',
        data: FormData.fromMap(data),
      );
    } catch (e) {
      throw AppException(
        UIErrorFormatter.getMessage(e),
        originalException: e,
      );
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
    var supabaseIdentityCreated = false;
    try {
      final normalizedEmail = email.trim().toLowerCase();

      // Fail fast on local duplicates before creating a Supabase identity.
      final preflightResponse =
          await _dio.post('/api/v1/auth/doctor/preflight', data: {
        'email': normalizedEmail,
        'license_number': licenseNumber.trim(),
      });
      final isExistingApplication = preflightResponse.data is Map &&
          preflightResponse.data['existing_application'] == true;

      // Supabase owns the password and sends the verification email when
      // Confirm Email is enabled for the project.
      final authResponse = await supabase.Supabase.instance.client.auth.signUp(
        email: normalizedEmail,
        password: password,
        data: {
          'role': 'doctor',
          'full_name': fullName.trim(),
        },
      );
      if (authResponse.user == null) {
        throw AppException(
          'Could not create your secure sign-in account. Please try again.',
        );
      }
      supabaseIdentityCreated = true;

      if (isExistingApplication) {
        return;
      }

      final Map<String, dynamic> mapData = {
        'full_name': fullName.trim(),
        'email': normalizedEmail,
        'specialty': specialty.trim(),
        'license_number': licenseNumber.trim(),
      };

      if (kIsWeb) {
        mapData['mdcn_license'] = MultipartFile.fromBytes(
          await mdcnLicense.readAsBytes(),
          filename: mdcnLicense.name.isEmpty ? 'license.jpg' : mdcnLicense.name,
          contentType: MediaType('image', 'jpeg'),
        );
        mapData['indemnity_certificate'] = MultipartFile.fromBytes(
          await indemnityCertificate.readAsBytes(),
          filename: indemnityCertificate.name.isEmpty
              ? 'indemnity.jpg'
              : indemnityCertificate.name,
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
          filename: indemnityCertificate.name.isEmpty
              ? 'indemnity.jpg'
              : indemnityCertificate.name,
          contentType: MediaType('image', 'jpeg'),
        );
      }

      final formData = FormData.fromMap(mapData);
      await _dio.post('/api/v1/auth/doctor/register', data: formData);
    } on supabase.AuthException catch (e) {
      throw AppException(e.message, originalException: e);
    } catch (e) {
      throw AppException(
        UIErrorFormatter.getMessage(e),
        originalException: e,
      );
    } finally {
      if (supabaseIdentityCreated) {
        try {
          await supabase.Supabase.instance.client.auth.signOut();
        } catch (_) {
          // The registration is still valid; local credential cleanup below
          // prevents an unapproved doctor session from remaining in the app.
        }
        await _clearStoredSession();
      }
    }
  }

  // --- SUBSCRIPTION ---

  Future<void> upgradeToPremium() async {
    try {
      await _dio.post('/api/v1/subscription/upgrade');
    } catch (e) {
      throw AppException(
        UIErrorFormatter.getMessage(e),
        originalException: e,
      );
    }
  }

  Future<void> cancelSubscription() async {
    try {
      final response =
          await _dio.post('/api/v1/subscription/cancel-subscription');
      if (response.statusCode != null && response.statusCode! >= 400) {
        throw AppException("Failed to cancel subscription.");
      }
    } on AppException {
      rethrow;
    } on DioException catch (e) {
      final data = e.response?.data;
      final msg = data is Map ? data['detail']?.toString() : null;
      throw AppException(
        msg ?? "Cancel subscription failed. Please try again.",
        originalException: e,
      );
    } catch (e) {
      throw AppException(
        "Cancel subscription failed. Please try again.",
        originalException: e,
      );
    }
  }

  Future<void> restoreSubscription() async {
    try {
      final response = await _dio.post('/api/v1/subscription/restore');
      if (response.statusCode != null && response.statusCode! >= 400) {
        throw AppException("Failed to restore subscription.");
      }
    } on AppException {
      rethrow;
    } on DioException catch (e) {
      final data = e.response?.data;
      final msg = data is Map ? data['detail']?.toString() : null;
      throw AppException(
        msg ?? "Restore subscription failed. Please try again.",
        originalException: e,
      );
    } catch (e) {
      throw AppException(
        "Restore subscription failed. Please try again.",
        originalException: e,
      );
    }
  }

  // --- SUPPORT ---

  Future<SupportSubmissionResult> sendSupportMessage({
    required String requestId,
    required String subject,
    required String message,
  }) async {
    try {
      final response = await _dio.post('/api/v1/support/contact', data: {
        'request_id': requestId,
        'subject': subject,
        'message': message,
      });
      final data = response.data;
      final responseRequestId =
          data is Map ? data['request_id']?.toString() : null;
      final status = data is Map ? data['status']?.toString() : null;
      if (responseRequestId != requestId || status != 'sent') {
        throw AppException(
          "We couldn't confirm that your message was sent. Please try again.",
        );
      }
      return SupportSubmissionResult(
        requestId: responseRequestId!,
        status: status!,
      );
    } catch (e) {
      if (e is AppException) rethrow;
      throw AppException(
        "We couldn't send your message right now. Your message hasn't been marked as sent. Please try again.",
        originalException: e,
      );
    }
  }

  // --- FAMILY PLAN ---

  Future<String> generateFamilyInvite() async {
    try {
      final response = await _dio.get('/api/v1/family/invite-code');
      return response.data['invite_code'];
    } catch (e) {
      throw AppException(
        UIErrorFormatter.getMessage(e),
        originalException: e,
      );
    }
  }

  Future<void> joinFamily(String inviteCode) async {
    try {
      await _dio.post('/api/v1/family/join', data: {
        'invite_code': inviteCode,
      });
    } catch (e) {
      throw AppException(
        UIErrorFormatter.getMessage(e),
        originalException: e,
      );
    }
  }
}
