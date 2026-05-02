class Appointment {
  final int id;
  final int doctorId;
  final String doctorName;
  final int patientId; // <--- NEW FIELD
  final String patientName; // <--- NEW FIELD
  final DateTime startTime;
  final String status;
  final String paymentStatus;
  final double amount;
  final String? notes;
  final bool hasReview;
  final String? paystackReference; // <--- NEW FIELD

  Appointment({
    required this.id,
    required this.doctorId,
    required this.doctorName,
    required this.patientId, // <--- Required
    required this.patientName, // <--- Required
    required this.startTime,
    required this.status,
    required this.paymentStatus,
    required this.amount,
    this.notes,
    this.hasReview = false,
    this.paystackReference,
  });

  factory Appointment.fromJson(Map<String, dynamic> json) {
    return Appointment(
      // The '?? 0' prevents the "Null is not a subtype of int" crash
      id: json['id'] ?? 0,
      doctorId: json['doctor_id'] ?? 0,
      doctorName: json['doctor_name'] ?? 'Doctor',

      // These safe defaults prevent crashes if backend data is missing
      patientId: json['patient_id'] ?? 0,
      patientName: json['patient_name'] ?? 'Patient',

      startTime: DateTime.parse(json['start_time']),
      status: json['status'] ?? 'pending',
      paymentStatus: json['payment_status'] ?? 'unpaid',
      amount: (json['amount'] as num?)?.toDouble() ?? 0.0,
      notes: json['notes'],
      hasReview: json['has_review'] ?? false,
      paystackReference: json['paystack_reference'],
    );
  }
}
