/// Data model matching the backend [VaultHistoryResponse] schema.
/// The [type] field discriminates between 'ai_summary' and 'consultation'.
class VaultRecord {
  final String id;
  final String type; // 'ai_summary' | 'consultation'
  final DateTime date;
  final DateTime? createdAt;
  final DateTime? updatedAt;
  final String? doctorName;
  final String topicOrReason;
  final String? details;
  final String? prescriptions;
  final String? referrals;

  const VaultRecord({
    required this.id,
    required this.type,
    required this.date,
    this.createdAt,
    this.updatedAt,
    this.doctorName,
    required this.topicOrReason,
    this.details,
    this.prescriptions,
    this.referrals,
  });

  factory VaultRecord.fromJson(Map<String, dynamic> json) {
    return VaultRecord(
      id: json['id'] as String,
      type: json['type'] as String,
      date: DateTime.parse(json['date'] as String),
      createdAt: json['created_at'] == null
          ? null
          : DateTime.parse(json['created_at'] as String),
      updatedAt: json['updated_at'] == null
          ? null
          : DateTime.parse(json['updated_at'] as String),
      doctorName: json['doctor_name'] as String?,
      topicOrReason: json['topic_or_reason'] as String? ?? '',
      details: json['details'] as String?,
      prescriptions: json['prescriptions'] as String?,
      referrals: json['referrals'] as String?,
    );
  }

  bool get isConsultation => type == 'consultation';
  bool get isAiSummary => type == 'ai_summary';
}
