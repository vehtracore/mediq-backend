import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'slot_model.dart';
import 'appointment_model.dart';

final appointmentRepositoryProvider = Provider<AppointmentRepository>((ref) {
  return AppointmentRepository(ref.watch(dioProvider));
});

class AppointmentRepository {
  final Dio _dio;

  AppointmentRepository(this._dio);

  // --- PATIENT METHODS ---

  Future<List<DoctorSlot>> getSlots(int doctorId) async {
    try {
      final response = await _dio.get(
        '/api/v1/appointments/doctors/$doctorId/slots',
      );
      final List<dynamic> data = response.data;
      return data.map((json) => DoctorSlot.fromJson(json)).toList();
    } catch (e) {
      throw Exception('Failed to fetch slots: $e');
    }
  }

  Future<Appointment> bookSlot({
    required int slotId,
    required String notes,
  }) async {
    try {
      final response = await _dio.post(
        '/api/v1/appointments/book',
        data: {"slot_id": slotId, "notes": notes},
      );
      return Appointment.fromJson(response.data);
    } on DioException catch (e) {
      if (e.response != null && e.response?.data != null) {
        final data = e.response?.data;
        if (data is Map && data.containsKey('detail')) {
          throw Exception(data['detail']);
        }
      }
      throw Exception("Failed to book appointment");
    } catch (e) {
      throw Exception("System error: $e");
    }
  }

  Future<List<Appointment>> getMyAppointments() async {
    try {
      final response = await _dio.get('/api/v1/appointments/my');
      final List<dynamic> data = response.data;
      return data.map((json) => Appointment.fromJson(json)).toList();
    } catch (e) {
      throw Exception('Failed to fetch appointments: $e');
    }
  }

  Future<void> markAsPaid(int appointmentId) async {
    try {
      await _dio.put('/api/v1/appointments/$appointmentId/pay');
    } catch (e) {
      throw Exception('Payment failed. Please try again.');
    }
  }

  Future<void> cancelMyAppointment(int id) async {
    try {
      await _dio.put('/api/v1/appointments/$id/cancel');
    } catch (e) {
      throw Exception('Failed to cancel appointment');
    }
  }

  // --- DOCTOR METHODS ---

  Future<List<Appointment>> getDoctorRequests() async {
    try {
      final response = await _dio.get('/api/v1/appointments/doctor/requests');
      final List<dynamic> data = response.data;
      return data.map((json) => Appointment.fromJson(json)).toList();
    } catch (e) {
      throw Exception('Failed to fetch requests: $e');
    }
  }

  Future<List<Appointment>> getDoctorConfirmedAppointments() async {
    try {
      final response = await _dio.get(
        '/api/v1/appointments/doctor/appointments',
      );
      final List<dynamic> data = response.data;
      return data.map((json) => Appointment.fromJson(json)).toList();
    } catch (e) {
      throw Exception('Failed to fetch schedule: $e');
    }
  }

  Future<void> acceptAppointment(int id) async {
    try {
      await _dio.put('/api/v1/appointments/doctor/appointments/$id/accept');
    } catch (e) {
      throw Exception('Failed to accept appointment');
    }
  }

  Future<void> declineAppointment(int id) async {
    try {
      await _dio.put('/api/v1/appointments/doctor/appointments/$id/decline');
    } catch (e) {
      throw Exception('Failed to decline appointment');
    }
  }

  Future<void> cancelAppointmentByDoctor(int id) async {
    try {
      await _dio.put('/api/v1/appointments/doctor/appointments/$id/cancel');
    } catch (e) {
      throw Exception('Failed to cancel appointment');
    }
  }

  // --- MISSING METHOD FIXED HERE ---
  Future<void> completeAppointment(int id) async {
    try {
      await _dio.put('/api/v1/appointments/doctor/appointments/$id/complete');
    } catch (e) {
      throw Exception('Failed to complete appointment');
    }
  }

  // --- GENERAL QUEUE METHODS ---

  Future<Appointment> bookGeneralConsultation(String notes) async {
    try {
      final response = await _dio.post(
        '/api/v1/appointments/book-general',
        data: {'notes': notes},
      );
      return Appointment.fromJson(response.data);
    } catch (e) {
      throw Exception('Failed to join queue: $e');
    }
  }

  Future<List<Appointment>> getGeneralQueue() async {
    try {
      final response = await _dio.get('/api/v1/appointments/doctor/queue');
      final List<dynamic> data = response.data;
      return data.map((json) => Appointment.fromJson(json)).toList();
    } catch (e) {
      throw Exception('Failed to fetch queue: $e');
    }
  }

  Future<void> claimAppointment(int id) async {
    try {
      await _dio.put('/api/v1/appointments/doctor/queue/$id/claim');
    } catch (e) {
      throw Exception('Failed to claim appointment');
    }
  }
}
