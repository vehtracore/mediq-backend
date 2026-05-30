/// Data model matching the backend [VaultHistoryResponse] schema.
/// The [type] field discriminates between 'ai_summary' and 'consultation'.
class VaultRecord {
  final String id;
  final String type; // 'ai_summary' | 'consultation'
  final DateTime date;
  final String? doctorName;
  final String topicOrReason;
  final String? details;
  final List<dynamic>? prescriptions;
  final List<dynamic>? referrals;

  const VaultRecord({
    required this.id,
    required this.type,
    required this.date,
    this.doctorName,
    required this.topicOrReason,
    this.details,
    this.prescriptions,
    this.referrals,
  });

  factory VaultRecord.fromJson(Map<String, dynamic> json) {
    // Safely coerce prescriptions / referrals — backend emits JSONB arrays or null
    List<dynamic>? _toList(dynamic raw) {
      if (raw == null) return null;
      if (raw is List) return raw;
      return null;
    }

    return VaultRecord(
      id: json['id'] as String,
      type: json['type'] as String,
      date: DateTime.parse(json['date'] as String),
      doctorName: json['doctor_name'] as String?,
      topicOrReason: json['topic_or_reason'] as String? ?? '',
      details: json['details'] as String?,
      prescriptions: _toList(json['prescriptions']),
      referrals: _toList(json['referrals']),
    );
  }

  bool get isConsultation => type == 'consultation';
  bool get isAiSummary => type == 'ai_summary';
}
