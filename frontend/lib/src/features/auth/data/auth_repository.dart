import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart' show kIsWeb; // ✅ Platform check
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart'; // ✅ Uses XFile
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'user_model.dart';
import '../../doctors/data/doctor_model.dart';

final authRepositoryProvider = Provider<AuthRepository>((ref) {
  return AuthRepository(ref.watch(dioProvider));
});

class AuthRepository {
  final Dio _dio;

  AuthRepository(this._dio);

  // --- Signup ---
  Future<Map<String, dynamic>> signUp({
    required String email,
    required String password,
    required String firstName,
    required String lastName,
    required DateTime dob,
    required String location,
  }) async {
    try {
      String dobString = dob.toIso8601String().split('T')[0];
      final response = await _dio.post(
        '/api/v1/auth/signup',
        data: {
          "email": email,
          "password": password,
          "first_name": firstName,
          "last_name": lastName,
          "dob": dobString,
          "location": location,
          "role": "patient",
        },
      );
      return response.data;
    } on DioException catch (e) {
      throw _handleError(e);
    } catch (e) {
      throw Exception("System error: $e");
    }
  }

  // --- Login ---
  Future<String> login({
    required String email,
    required String password,
  }) async {
    try {
      final response = await _dio.post(
        '/api/v1/auth/login',
        data: {"email": email, "password": password},
      );
      return response.data['access_token'];
    } on DioException catch (e) {
      if (e.response?.statusCode == 401) {
        throw Exception("Invalid email or password");
      }
      throw _handleError(e);
    } catch (e) {
      throw Exception("System error: $e");
    }
  }

  // --- Get User Profile ---
  Future<User> getUserProfile() async {
    try {
      final response = await _dio.get('/api/v1/auth/me');
      return User.fromJson(response.data);
    } on DioException catch (e) {
      throw Exception("Failed to load profile: ${e.message}");
    } catch (e) {
      throw Exception("System error: $e");
    }
  }

  // --- 🚀 UPDATE PROFILE (WEB SAFE + BOUNDARY FIX) ---
  Future<User> updateProfile(Map<String, dynamic> data,
      {XFile? profileImage}) async {
    try {
      Response response;

      if (profileImage != null) {
        // ✅ Create FormData
        final formData = FormData.fromMap(data);

        // ✅ WEB VS MOBILE SPLIT
        if (kIsWeb) {
          // ON WEB: Read bytes directly
          final bytes = await profileImage.readAsBytes();
          formData.files.add(MapEntry(
            'profile_image',
            MultipartFile.fromBytes(bytes, filename: profileImage.name),
          ));
        } else {
          // ON MOBILE: Read from path
          formData.files.add(MapEntry(
            'profile_image',
            await MultipartFile.fromFile(profileImage.path,
                filename: profileImage.name),
          ));
        }

        // ⚡ CRITICAL FIX: Set contentType to null.
        // This forces Dio to let the Browser generate the correct boundary string.
        response = await _dio.put(
          '/api/v1/auth/me',
          data: formData,
          options: Options(contentType: null), // <--- THE FIX for XMLHttpRequest Error
        );
      } else {
        // Standard JSON update (keep default headers)
        response = await _dio.put(
          '/api/v1/auth/me',
          data: data,
        );
      }

      return User.fromJson(response.data);
    } on DioException catch (e) {
      throw _handleError(e);
    } catch (e) {
      throw Exception("System error: $e");
    }
  }

  // --- Register Doctor ---
  Future<void> registerDoctor({
    required String fullName,
    required String email,
    required String password,
    required String specialty,
    required String licenseNumber,
  }) async {
    try {
      await _dio.post(
        '/api/v1/auth/doctor/register',
        data: {
          "full_name": fullName,
          "email": email,
          "password": password,
          "specialty": specialty,
          "license_number": licenseNumber,
        },
      );
    } on DioException catch (e) {
      throw _handleError(e);
    } catch (e) {
      throw Exception("System error: $e");
    }
  }

  // --- Get Doctor Profile ---
  Future<Doctor> getMyDoctorProfile() async {
    try {
      final response = await _dio.get('/api/v1/auth/my-doctor-profile');
      return Doctor.fromJson(response.data);
    } catch (e) {
      throw Exception('Failed to load doctor profile');
    }
  }

  // --- Upgrade Subscription ---
  Future<void> upgradeToPremium() async {
    try {
      await _dio.post('/api/v1/subscription/upgrade');
    } on DioException catch (e) {
      throw _handleError(e);
    } catch (e) {
      throw Exception("System error: $e");
    }
  }

  // --- Get Current User (Helper) ---
  Future<User?> getCurrentUser() async {
    try {
      final response = await _dio.get('/api/v1/auth/me');
      return User.fromJson(response.data);
    } catch (e) {
      // Return null instead of throwing, useful for splash screens
      return null;
    }
  }

  Exception _handleError(DioException e) {
    String errorMessage = "An unexpected error occurred";
    if (e.response != null) {
      if (e.response!.data is Map && e.response!.data.containsKey('detail')) {
        errorMessage = e.response!.data['detail'];
      } else {
        errorMessage = "Server error: ${e.response!.statusCode}";
      }
    } else {
      errorMessage = "Connection error. Please check your internet.";
    }
    return Exception(errorMessage);
  }
}