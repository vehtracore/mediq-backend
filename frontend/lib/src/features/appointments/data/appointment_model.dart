import 'package:flutter/foundation.dart';

class Appointment {
  static const generalQueueType = 'general_queue';
  static const specialistScheduledType = 'specialist_scheduled';
  static const vipRequestType = 'vip_request';

  final int id;
  // These are the backend's integer relational PKs.
  // The backend's AppointmentResponse schema now emits them explicitly.
  // Safe fallback to 0 prevents type-cast crashes if a legacy response omits them.
  final int? doctorId;
  final String? appointmentType;
  final String doctorName;
  final int? patientId;
  final String patientName;
  final DateTime?
      startTime; // null for VIP requests pending doctor's time proposal
  final DateTime? patientJoinedAt;
  final DateTime? doctorJoinedAt;
  final DateTime? consultationStartedAt;
  final DateTime? noShowMarkedAt;
  final String? refundStatus;
  final String status;
  final String paymentStatus;
  final bool isAcknowledged;
  final double amount;
  final String? notes;
  final bool hasReview;
  final String? paystackReference;
  final String? prescription;

  Appointment({
    required this.id,
    this.doctorId,
    this.appointmentType,
    required this.doctorName,
    this.patientId,
    required this.patientName,
    this.startTime,
    this.patientJoinedAt,
    this.doctorJoinedAt,
    this.consultationStartedAt,
    this.noShowMarkedAt,
    this.refundStatus,
    required this.status,
    required this.paymentStatus,
    this.isAcknowledged = false,
    this.amount = 0.0,
    this.notes,
    this.hasReview = false,
    this.paystackReference,
    this.prescription,
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
    int? safeInt(dynamic v) {
      if (v == null) return null;
      if (v is int) return v;
      if (v is String) return int.tryParse(v);
      return null;
    }

    return Appointment(
      id: safeInt(json['id']) ?? 0,
      doctorId: safeInt(json['doctor_id']),
      appointmentType: json['appointment_type'] as String?,
      doctorName: (json['doctor_name'] as String?) ?? 'Doctor',
      patientId: safeInt(json['patient_id']),
      patientName: (json['patient_name'] as String?) ?? 'Patient',
      startTime: json['start_time'] != null
          ? DateTime.parse(json['start_time'] as String).toLocal()
          : null,
      patientJoinedAt: json['patient_joined_at'] != null
          ? DateTime.parse(json['patient_joined_at'] as String).toLocal()
          : null,
      doctorJoinedAt: json['doctor_joined_at'] != null
          ? DateTime.parse(json['doctor_joined_at'] as String).toLocal()
          : null,
      consultationStartedAt: json['consultation_started_at'] != null
          ? DateTime.parse(json['consultation_started_at'] as String).toLocal()
          : null,
      noShowMarkedAt: json['no_show_marked_at'] != null
          ? DateTime.parse(json['no_show_marked_at'] as String).toLocal()
          : null,
      refundStatus: json['refund_status'] as String?,
      status: (json['status'] as String?) ?? 'pending',
      paymentStatus: (json['payment_status'] as String?) ?? 'unpaid',
      isAcknowledged: json['is_acknowledged'] == true,
      amount: (json['amount'] as num?)?.toDouble() ?? 0.0,
      notes: json['notes'] as String?,
      hasReview: (json['has_review'] as bool?) ?? false,
      paystackReference: json['paystack_reference'] as String?,
      prescription: json['prescription'] as String?,
    );
  }

  bool get isGeneralQueue => appointmentType == generalQueueType;
  bool get isSpecialistScheduled => appointmentType == specialistScheduledType;
  bool get isVipRequest => appointmentType == vipRequestType;
  bool get isNoShow => const {
        'patient_no_show',
        'doctor_no_show',
        'both_no_show',
      }.contains(status);

  bool get canPatientCancel {
    final cancellableStatus = status == 'pending' ||
        status == 'awaiting_payment' ||
        status == 'confirmed';
    if (!cancellableStatus) return false;

    if ((isGeneralQueue || appointmentType == null) && status == 'confirmed') {
      return false;
    }

    if (isSpecialistScheduled || isVipRequest) {
      final scheduledStart = startTime;
      if (scheduledStart != null && !DateTime.now().isBefore(scheduledStart)) {
        return false;
      }
    }
    return true;
  }

  bool get isConsultationUnlocked {
    if (status != 'confirmed') return false;
    final actualStart = consultationStartedAt;
    if (actualStart != null) {
      return DateTime.now().isBefore(
        actualStart.add(const Duration(minutes: 40)),
      );
    }
    final scheduledStart = startTime;
    if (scheduledStart == null) return false;
    final now = DateTime.now();
    if (isGeneralQueue) {
      return !now.isBefore(scheduledStart) &&
          now.isBefore(scheduledStart.add(const Duration(minutes: 5)));
    }
    final unlockTime = scheduledStart.subtract(const Duration(minutes: 10));
    final joinDeadline = scheduledStart.add(const Duration(minutes: 15));
    return !now.isBefore(unlockTime) && now.isBefore(joinDeadline);
  }

  bool get canPatientPay {
    if (paymentStatus != 'unpaid') return false;
    return isVipRequest && status == 'awaiting_payment';
  }

  String? get paymentTransactionType {
    if (isGeneralQueue) return 'gp_consult';
    if (isSpecialistScheduled) return 'specialist_consult';
    if (isVipRequest) return 'vip_request';
    return null;
  }

  String get typeLabel {
    if (isGeneralQueue) return 'General Queue';
    if (isSpecialistScheduled) return 'Specialist Session';
    if (isVipRequest) return 'VIP Request';
    return 'Legacy Appointment';
  }

  String get statusLabel => status.replaceAll('_', ' ').toUpperCase();
}
