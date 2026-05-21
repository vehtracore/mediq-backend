import 'package:flutter/foundation.dart';

class Appointment {
  final int id;
  // These are the backend's integer relational PKs.
  // The backend's AppointmentResponse schema now emits them explicitly.
  // Safe fallback to 0 prevents type-cast crashes if a legacy response omits them.
  final int? doctorId;
  final String doctorName;
  final int? patientId;
  final String patientName;
  final DateTime startTime;
  final String status;
  final String paymentStatus;
  final double amount;
  final String? notes;
  final bool hasReview;
  final String? paystackReference;

  Appointment({
    required this.id,
    this.doctorId,
    required this.doctorName,
    this.patientId,
    required this.patientName,
    required this.startTime,
    required this.status,
    required this.paymentStatus,
    required this.amount,
    this.notes,
    this.hasReview = false,
    this.paystackReference,
  });

  factory Appointment.fromJson(Map<String, dynamic> json) {
    // ── Debug handshake: log the raw payload so UUID/int mismatches are visible ──
    if (kDebugMode) {
      debugPrint(
        '📦 [Appointment.fromJson] id=${json["id"]} '
        'doctor_id=${json["doctor_id"]} (${json["doctor_id"].runtimeType}) '
        'patient_id=${json["patient_id"]} (${json["patient_id"].runtimeType}) '
        'status=${json["status"]} payment=${json["payment_status"]}',
      );
    }

    // Safe int parsing: handles both int and string representations gracefully.
    int? _safeInt(dynamic v) {
      if (v == null) return null;
      if (v is int) return v;
      if (v is String) return int.tryParse(v);
      return null;
    }

    return Appointment(
      id: _safeInt(json['id']) ?? 0,
      doctorId: _safeInt(json['doctor_id']),
      doctorName: (json['doctor_name'] as String?) ?? 'Doctor',
      patientId: _safeInt(json['patient_id']),
      patientName: (json['patient_name'] as String?) ?? 'Patient',
      startTime: DateTime.parse(json['start_time'] as String),
      status: (json['status'] as String?) ?? 'pending',
      paymentStatus: (json['payment_status'] as String?) ?? 'unpaid',
      amount: (json['amount'] as num?)?.toDouble() ?? 0.0,
      notes: json['notes'] as String?,
      hasReview: (json['has_review'] as bool?) ?? false,
      paystackReference: json['paystack_reference'] as String?,
    );
  }
}
