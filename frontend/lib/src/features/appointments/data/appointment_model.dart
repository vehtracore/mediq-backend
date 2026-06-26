import 'package:flutter/foundation.dart';

class Appointment {
  static const generalQueueType = 'general_queue';
  static const specialistScheduledType = 'specialist_scheduled';
  static const vipRequestType = 'vip_request';
  static const consultationDuration = Duration(minutes: 30);
  static const consultationMessageGrace = Duration(minutes: 10);
  static const scheduledRoomEarlyAccess = Duration(minutes: 10);
  static const scheduledJoinGrace = Duration(minutes: 15);
  static const generalQueueJoinGrace = Duration(minutes: 5);

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
    // â”€â”€ Debug handshake: log the raw payload so UUID/int mismatches are visible â”€â”€
    if (kDebugMode) {
      debugPrint(
        'ðŸ“¦ [Appointment.fromJson] id=${json["id"]} '
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

  DateTime? get consultationMessagesEndAt {
    final actualStart = consultationStartedAt;
    if (actualStart == null) return null;
    return actualStart.add(consultationDuration + consultationMessageGrace);
  }

  DateTime? get roomUnlockAt {
    final scheduledStart = startTime;
    if (scheduledStart == null) return null;
    if (isGeneralQueue || appointmentType == null) return scheduledStart;
    return scheduledStart.subtract(scheduledRoomEarlyAccess);
  }

  DateTime? get attendanceDeadlineAt {
    final scheduledStart = startTime;
    if (scheduledStart == null) return null;
    if (isGeneralQueue || appointmentType == null) {
      return scheduledStart.add(generalQueueJoinGrace);
    }
    return scheduledStart.add(scheduledJoinGrace);
  }

  bool get hasConsultationStarted => consultationStartedAt != null;

  bool get hasConsultationOpened {
    if (status != 'confirmed') return false;
    if (hasConsultationStarted) return true;
    final unlockAt = roomUnlockAt;
    if (unlockAt == null) return false;
    return !DateTime.now().isBefore(unlockAt);
  }

  bool get isConsultationClosed {
    if (status != 'confirmed') return false;
    final actualEnd = consultationMessagesEndAt;
    if (actualEnd != null) {
      return !DateTime.now().isBefore(actualEnd);
    }
    final deadline = attendanceDeadlineAt;
    if (deadline == null) return false;
    return !DateTime.now().isBefore(deadline);
  }

  bool get isConsultationOpen {
    if (status != 'confirmed' || paymentStatus != 'paid') return false;
    if (isConsultationClosed) return false;

    if (hasConsultationStarted) return true;

    final unlockAt = roomUnlockAt;
    final deadline = attendanceDeadlineAt;
    if (unlockAt == null || deadline == null) return false;
    final now = DateTime.now();
    return !now.isBefore(unlockAt) && now.isBefore(deadline);
  }

  bool get isConsultationLocked {
    if (status != 'confirmed' || isConsultationClosed) return false;
    final unlockAt = roomUnlockAt;
    if (unlockAt == null) return false;
    return DateTime.now().isBefore(unlockAt);
  }

  bool get canDoctorWrapUp =>
      status == 'confirmed' &&
      paymentStatus == 'paid' &&
      hasConsultationStarted;

  bool get canDoctorCancel {
    if (status == 'awaiting_payment') return true;
    if (status != 'confirmed') return false;
    if (isGeneralQueue || appointmentType == null) return false;
    return !hasConsultationOpened;
  }

  DateTime? get nextConsultationBoundary {
    final now = DateTime.now();
    final candidates = <DateTime?>[
      roomUnlockAt,
      startTime,
      attendanceDeadlineAt,
      consultationMessagesEndAt,
    ].whereType<DateTime>().where((value) => value.isAfter(now)).toList()
      ..sort();
    if (candidates.isEmpty) return null;
    return candidates.first;
  }

  bool get canPatientCancel {
    final cancellableStatus = status == 'pending' ||
        status == 'awaiting_payment' ||
        status == 'confirmed';
    if (!cancellableStatus) return false;

    if ((isGeneralQueue || appointmentType == null) && status == 'confirmed') {
      return false;
    }

    if ((isSpecialistScheduled || isVipRequest) &&
        status == 'confirmed' &&
        hasConsultationOpened) {
      return false;
    }
    return true;
  }

  bool get isConsultationUnlocked => isConsultationOpen;

  bool get canPatientPay {
    if (paymentStatus != 'unpaid') return false;
    return isVipRequest && status == 'awaiting_payment';
  }

  DateTime? get complaintWindowEndsAt {
    final messagesEndAt = consultationMessagesEndAt;
    if (messagesEndAt == null) return null;
    return messagesEndAt.add(const Duration(hours: 24));
  }

  bool get canPatientReportIssue {
    if (status != 'completed' || paymentStatus != 'paid') return false;
    if (refundStatus != null && refundStatus != 'rejected') return false;
    final windowEndsAt = complaintWindowEndsAt;
    if (windowEndsAt == null) return false;
    return DateTime.now().isBefore(windowEndsAt);
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
