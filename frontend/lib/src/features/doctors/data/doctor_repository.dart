
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'doctor_model.dart';

final doctorRepositoryProvider = Provider<DoctorRepository>((ref) => DoctorRepository(ref.watch(dioProvider)));

class DoctorRepository {
  final Dio _dio;
  DoctorRepository(this._dio);

  Future<List<Doctor>> getDoctors() async {
    final response = await _dio.get('/api/v1/doctors/');
    return (response.data as List).map((json) => Doctor.fromJson(json)).toList();
  }

  Future<void> updateDoctorProfile({String? bio, double? hourlyRate, int? yearsExperience}) async {
    await _dio.put('/api/v1/doctors/me', data: {
      if (bio != null) "bio": bio,
      if (hourlyRate != null) "hourly_rate": hourlyRate,
      if (yearsExperience != null) "years_experience": yearsExperience
    });
  }

  Future<Map<String, dynamic>> getDoctorStats() async {
    final response = await _dio.get('/api/v1/doctors/stats');
    return response.data;
  }
  
  Future<void> createSlot({required int doctorId, required DateTime startTime}) async {
    await _dio.post('/api/v1/appointments/slots', data: {"doctor_id": doctorId, "start_time": startTime.toIso8601String()});
  }
}
