
class Appointment {
  final int id;
  final String doctorName;
  final String status;
  final String paymentStatus;
  final DateTime startTime;
  final String? notes;
  final double amount;
  final bool hasReview; // <--- NEW FIELD

  Appointment({
    required this.id,
    required this.doctorName,
    required this.status,
    required this.paymentStatus,
    required this.startTime,
    this.notes,
    this.amount = 0.0,
    this.hasReview = false, // Default false
  });

  factory Appointment.fromJson(Map<String, dynamic> json) {
    return Appointment(
      id: json['id'],
      doctorName: json['doctor_name'] ?? 'Unknown',
      status: json['status'],
      paymentStatus: json['payment_status'],
      startTime: DateTime.parse(json['start_time']),
      notes: json['notes'],
      amount: (json['amount'] as num?)?.toDouble() ?? 0.0,
      hasReview: json['has_review'] ?? false, // Parse it
    );
  }
}
