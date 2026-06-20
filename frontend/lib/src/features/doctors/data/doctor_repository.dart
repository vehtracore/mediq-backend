import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'doctor_model.dart';

final doctorRepositoryProvider = Provider<DoctorRepository>(
    (ref) => DoctorRepository(ref.watch(dioProvider)));

class DoctorRepository {
  final Dio _dio;
  DoctorRepository(this._dio);

  Future<List<Doctor>> getDoctors() async {
    final response = await _dio.get('/api/v1/doctors/');
    return (response.data as List)
        .map((json) => Doctor.fromJson(json))
        .toList();
  }

  Future<Doctor> getDoctorById(int doctorId) async {
    final response = await _dio.get('/api/v1/doctors/$doctorId');
    return Doctor.fromJson(response.data);
  }

  Future<void> updateDoctorProfile(
      {String? bio,
      double? consultationFee,
      int? consultationDurationMinutes,
      int? yearsExperience,
      String? imageUrl}) async {
    await _dio.put('/api/v1/doctors/me', data: {
      if (bio != null) "bio": bio,
      if (consultationFee != null) "consultation_fee": consultationFee,
      if (consultationDurationMinutes != null)
        "consultation_duration_minutes": consultationDurationMinutes,
      if (yearsExperience != null) "years_experience": yearsExperience,
      if (imageUrl != null) "image_url": imageUrl,
    });
  }

  Future<Map<String, dynamic>> getDoctorStats() async {
    final response = await _dio.get('/api/v1/doctors/stats');
    return response.data;
  }

  Future<void> createSlot(
      {required int doctorId, required DateTime startTime}) async {
    try {
      await _dio.post(
        '/api/v1/appointments/slots',
        data: {
          "doctor_id": doctorId,
          "start_time": startTime.toUtc().toIso8601String(),
        },
      );
    } on DioException catch (e) {
      final detail = e.response?.data is Map
          ? e.response?.data['detail'] ?? e.message
          : e.message;
      throw Exception(detail ?? 'Failed to create slot');
    }
  }

  Future<void> deleteSlot(int slotId) async {
    try {
      await _dio.delete('/api/v1/appointments/slots/$slotId');
    } on DioException catch (e) {
      final detail = e.response?.data is Map
          ? e.response?.data['detail'] ?? e.message
          : e.message;
      throw Exception(detail ?? 'Failed to delete slot');
    } catch (e) {
      throw Exception('Failed to delete slot: $e');
    }
  }

  /// Links a bank account to the doctor's Paystack subaccount.
  /// Throws [DioException] on failure — the error message from Paystack is
  /// forwarded verbatim inside [DioException.response.data['detail']].
  Future<void> updatePayoutSettings({
    required String bankCode,
    required String accountNumber,
  }) async {
    await _dio.put('/api/v1/doctors/me/payout-settings', data: {
      "bank_code": bankCode,
      "account_number": accountNumber,
    });
  }
}
