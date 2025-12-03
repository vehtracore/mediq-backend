class DoctorSlot {
  final int id;
  final int doctorId;
  final DateTime startTime;
  final bool isBooked;

  DoctorSlot({
    required this.id,
    required this.doctorId,
    required this.startTime,
    required this.isBooked,
  });

  factory DoctorSlot.fromJson(Map<String, dynamic> json) {
    return DoctorSlot(
      id: json['id'],
      doctorId: json['doctor_id'],
      startTime: DateTime.parse(json['start_time']),
      isBooked: json['is_booked'] ?? false,
    );
  }
}
