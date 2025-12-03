import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/core/api/api_constants.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import '../../doctors/data/doctor_model.dart';

// --- User Model ---
class User {
  final int id;
  final String email;
  final String firstName;
  final String lastName;
  final DateTime dob;
  final String? location;
  final String role;
  final String plan;
  // --- NEW FIELD ---
  final bool isBanned;

  String get fullName => "$firstName $lastName";
  bool get isPremium => plan == 'premium';

  User({
    required this.id,
    required this.email,
    required this.firstName,
    required this.lastName,
    required this.dob,
    this.location,
    required this.role,
    required this.plan,
    required this.isBanned, // Required in constructor
  });

  factory User.fromJson(Map<String, dynamic> json) {
    return User(
      id: json['id'],
      email: json['email'],
      firstName: json['first_name'],
      lastName: json['last_name'],
      dob: DateTime.parse(json['dob']),
      location: json['location'],
      role: json['role'] ?? 'patient',
      plan: json['plan'] ?? 'free',
      // Parse is_banned (default to false if missing)
      isBanned: json['is_banned'] ?? false,
    );
  }
}

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
        ApiConstants.signupEndpoint,
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

  // --- Update Profile ---
  Future<User> updateProfile({
    required String firstName,
    required String lastName,
    required String location,
  }) async {
    try {
      final response = await _dio.put(
        '/api/v1/auth/me',
        data: {
          "first_name": firstName,
          "last_name": lastName,
          "location": location,
        },
      );
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

  // --- UPGRADE SUBSCRIPTION ---
  Future<void> upgradeToPremium() async {
    try {
      await _dio.post('/api/v1/subscription/upgrade');
    } on DioException catch (e) {
      throw _handleError(e);
    } catch (e) {
      throw Exception("System error: $e");
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
