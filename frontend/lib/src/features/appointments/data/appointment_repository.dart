import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'package:supabase_flutter/supabase_flutter.dart' hide User;
import 'slot_model.dart';
import 'appointment_model.dart';

final appointmentRepositoryProvider = Provider<AppointmentRepository>((ref) {
  return AppointmentRepository(ref.watch(dioProvider));
});

class AppointmentRepository {
  final Dio _dio;

  AppointmentRepository(this._dio);

  // ── Internal helper: log the current Supabase session state before any call ──
  void _logAuthHandshake(String endpoint) {
    if (!kDebugMode) return;
    final session = Supabase.instance.client.auth.currentSession;
    final user = Supabase.instance.client.auth.currentUser;
    debugPrint(
      '🔐 [AUTH HANDSHAKE] → $endpoint\n'
      '   supabase_uid : ${user?.id ?? "NULL — not logged in!"}\n'
      '   email        : ${user?.email ?? "N/A"}\n'
      '   token_present: ${session?.accessToken != null}\n'
      '   token_expires: ${session?.expiresAt != null ? DateTime.fromMillisecondsSinceEpoch(session!.expiresAt! * 1000).toIso8601String() : "N/A"}',
    );
  }

  // ── Internal helper: log the raw JSON response ──
  void _logResponse(String endpoint, dynamic data) {
    if (!kDebugMode) return;
    debugPrint('📬 [RAW RESPONSE] ← $endpoint\n   data: $data');
  }

  // --- PATIENT METHODS ---

  Future<List<DoctorSlot>> getSlots(int doctorId) async {
    const ep = 'GET /api/v1/appointments/doctors/:id/slots';
    _logAuthHandshake(ep);
    try {
      final response = await _dio.get(
        '/api/v1/appointments/doctors/$doctorId/slots',
      );
      _logResponse(ep, response.data);
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
    const ep = 'POST /api/v1/appointments/book';
    _logAuthHandshake(ep);
    debugPrint('📤 [PAYLOAD] → $ep  slot_id=$slotId notes="$notes"');
    try {
      final response = await _dio.post(
        '/api/v1/appointments/book',
        data: {"slot_id": slotId, "notes": notes},
      );
      _logResponse(ep, response.data);
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
    const ep = 'GET /api/v1/appointments/my';
    _logAuthHandshake(ep);
    try {
      final response = await _dio.get('/api/v1/appointments/my');
      _logResponse(ep, response.data);
      final List<dynamic> data = response.data;
      return data.map((json) => Appointment.fromJson(json)).toList();
    } catch (e) {
      throw Exception('Failed to fetch appointments: $e');
    }
  }

  Future<void> markAsPaid(int appointmentId) async {
    const ep = 'PUT /api/v1/appointments/:id/pay';
    _logAuthHandshake(ep);
    try {
      await _dio.put('/api/v1/appointments/$appointmentId/pay');
    } catch (e) {
      throw Exception('Payment failed. Please try again.');
    }
  }

  Future<void> cancelMyAppointment(int id) async {
    const ep = 'PUT /api/v1/appointments/:id/cancel';
    _logAuthHandshake(ep);
    try {
      await _dio.put('/api/v1/appointments/$id/cancel');
    } catch (e) {
      throw Exception('Failed to cancel appointment');
    }
  }

  // --- DOCTOR METHODS ---

  Future<List<Appointment>> getDoctorRequests() async {
    const ep = 'GET /api/v1/appointments/doctor/requests';
    _logAuthHandshake(ep);
    try {
      final response = await _dio.get('/api/v1/appointments/doctor/requests');
      _logResponse(ep, response.data);
      final List<dynamic> data = response.data;
      return data.map((json) => Appointment.fromJson(json)).toList();
    } catch (e) {
      throw Exception('Failed to fetch requests: $e');
    }
  }

  Future<List<Appointment>> getDoctorConfirmedAppointments() async {
    const ep = 'GET /api/v1/appointments/doctor/appointments';
    _logAuthHandshake(ep);
    try {
      final response = await _dio.get(
        '/api/v1/appointments/doctor/appointments',
      );
      _logResponse(ep, response.data);
      final List<dynamic> data = response.data;
      return data.map((json) => Appointment.fromJson(json)).toList();
    } catch (e) {
      throw Exception('Failed to fetch schedule: $e');
    }
  }

  Future<void> acceptAppointment(int id) async {
    _logAuthHandshake('PUT /api/v1/appointments/doctor/appointments/:id/accept');
    try {
      await _dio.put('/api/v1/appointments/doctor/appointments/$id/accept');
    } catch (e) {
      throw Exception('Failed to accept appointment');
    }
  }

  Future<void> declineAppointment(int id) async {
    _logAuthHandshake('PUT /api/v1/appointments/doctor/appointments/:id/decline');
    try {
      await _dio.put('/api/v1/appointments/doctor/appointments/$id/decline');
    } catch (e) {
      throw Exception('Failed to decline appointment');
    }
  }

  Future<void> cancelAppointmentByDoctor(int id) async {
    _logAuthHandshake('PUT /api/v1/appointments/doctor/appointments/:id/cancel');
    try {
      await _dio.put('/api/v1/appointments/doctor/appointments/$id/cancel');
    } catch (e) {
      throw Exception('Failed to cancel appointment');
    }
  }

  Future<void> completeAppointment(int id) async {
    _logAuthHandshake('PUT /api/v1/appointments/doctor/appointments/:id/complete');
    try {
      await _dio.put('/api/v1/appointments/doctor/appointments/$id/complete');
    } catch (e) {
      throw Exception('Failed to complete appointment');
    }
  }

  Future<void> referAppointment({
    required int id,
    required String hospitalName,
    required String note,
  }) async {
    _logAuthHandshake('POST /api/v1/appointments/doctor/appointments/:id/refer');
    try {
      await _dio.post(
        '/api/v1/appointments/doctor/appointments/$id/refer',
        data: {'hospital_name': hospitalName, 'note': note},
      );
    } on DioException catch (e) {
      final detail = e.response?.data?['detail'];
      throw Exception(detail ?? 'Failed to submit referral');
    } catch (e) {
      throw Exception('Failed to submit referral: $e');
    }
  }

  Future<void> prescribeAppointment({
    required int id,
    required String prescription,
  }) async {
    _logAuthHandshake('PUT /api/v1/appointments/doctor/appointments/:id/prescribe');
    try {
      await _dio.put(
        '/api/v1/appointments/doctor/appointments/$id/prescribe',
        data: {'prescription': prescription},
      );
    } on DioException catch (e) {
      final detail = e.response?.data?['detail'];
      throw Exception(detail ?? 'Failed to save prescription');
    } catch (e) {
      throw Exception('Failed to save prescription: $e');
    }
  }

  // --- GENERAL QUEUE METHODS ---

  Future<Appointment> bookGeneralConsultation(String notes) async {
    const ep = 'POST /api/v1/appointments/book-general';
    _logAuthHandshake(ep);
    debugPrint('📤 [PAYLOAD] → $ep  notes="$notes"');
    try {
      final response = await _dio.post(
        '/api/v1/appointments/book-general',
        data: {'notes': notes},
      );
      _logResponse(ep, response.data);
      return Appointment.fromJson(response.data);
    } catch (e) {
      throw Exception('Failed to join queue: $e');
    }
  }

  Future<List<Appointment>> getGeneralQueue() async {
    const ep = 'GET /api/v1/appointments/doctor/queue';
    _logAuthHandshake(ep);
    try {
      final response = await _dio.get('/api/v1/appointments/doctor/queue');
      _logResponse(ep, response.data);
      final List<dynamic> data = response.data;
      return data.map((json) => Appointment.fromJson(json)).toList();
    } catch (e) {
      throw Exception('Failed to fetch queue: $e');
    }
  }

  Future<void> claimAppointment(int id) async {
    _logAuthHandshake('PUT /api/v1/appointments/doctor/queue/:id/claim');
    try {
      await _dio.put('/api/v1/appointments/doctor/queue/$id/claim');
    } catch (e) {
      throw Exception('Failed to claim appointment');
    }
  }

  Future<void> acknowledgeAppointment(int appointmentId) async {
    final ep = 'PATCH /api/v1/appointments/$appointmentId/acknowledge';
    _logAuthHandshake(ep);
    try {
      final response = await _dio.patch('/api/v1/appointments/$appointmentId/acknowledge');
      _logResponse(ep, response.data);
    } catch (e) {
      throw Exception('Failed to acknowledge appointment: $e');
    }
  }

  Future<void> proposeAppointmentTime(int appointmentId, DateTime proposedTime) async {
    final ep = 'PATCH /api/v1/appointments/$appointmentId/propose';
    _logAuthHandshake(ep);
    try {
      final response = await _dio.patch(
        '/api/v1/appointments/$appointmentId/propose',
        data: {'proposed_time': proposedTime.toUtc().toIso8601String()},
      );
      _logResponse(ep, response.data);
    } catch (e) {
      throw Exception('Failed to propose appointment time: $e');
    }
  }

  Future<void> requestVIPAppointment({
    required int doctorId,
    required String preferredTime,
    required String notes,
  }) async {
    final ep = 'POST /api/v1/appointments/request';
    _logAuthHandshake(ep);
    try {
      final response = await _dio.post(
        '/api/v1/appointments/request',
        data: {
          'doctor_id': doctorId,
          'preferred_time': preferredTime,
          'notes': notes,
        },
      );
      _logResponse(ep, response.data);
    } catch (e) {
      throw Exception('Failed to send VIP request: $e');
    }
  }
}
