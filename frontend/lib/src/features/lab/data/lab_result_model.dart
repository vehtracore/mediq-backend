class ReadingDetail {
  final String value;
  final String color;

  ReadingDetail({required this.value, required this.color});

  factory ReadingDetail.fromJson(Map<String, dynamic> json) {
    return ReadingDetail(
      value: json['value'] ?? 'Unknown',
      color: json['color'] ?? 'Unknown',
    );
  }
}

class LabReading {
  final ReadingDetail? leukocytes;
  final ReadingDetail? nitrites;
  final ReadingDetail? urobilinogen;
  final ReadingDetail? protein;
  final ReadingDetail? ph;
  final ReadingDetail? blood;
  final ReadingDetail? specificGravity;
  final ReadingDetail? ketones;
  final ReadingDetail? bilirubin;
  final ReadingDetail? glucose;

  LabReading({
    this.leukocytes,
    this.nitrites,
    this.urobilinogen,
    this.protein,
    this.ph,
    this.blood,
    this.specificGravity,
    this.ketones,
    this.bilirubin,
    this.glucose,
  });

  factory LabReading.fromJson(Map<String, dynamic> json) {
    return LabReading(
      leukocytes: json['leukocytes'] != null ? ReadingDetail.fromJson(json['leukocytes']) : null,
      nitrites: json['nitrites'] != null ? ReadingDetail.fromJson(json['nitrites']) : null,
      urobilinogen: json['urobilinogen'] != null ? ReadingDetail.fromJson(json['urobilinogen']) : null,
      protein: json['protein'] != null ? ReadingDetail.fromJson(json['protein']) : null,
      ph: json['ph'] != null ? ReadingDetail.fromJson(json['ph']) : null,
      blood: json['blood'] != null ? ReadingDetail.fromJson(json['blood']) : null,
      specificGravity: json['specific_gravity'] != null ? ReadingDetail.fromJson(json['specific_gravity']) : null,
      ketones: json['ketones'] != null ? ReadingDetail.fromJson(json['ketones']) : null,
      bilirubin: json['bilirubin'] != null ? ReadingDetail.fromJson(json['bilirubin']) : null,
      glucose: json['glucose'] != null ? ReadingDetail.fromJson(json['glucose']) : null,
    );
  }
}

class LabAnalysisResponse {
  final String status;
  final String? lightingScore;
  final LabReading? readings;
  final String? notes;
  final int? recordId;
  final String? reason;

  LabAnalysisResponse({
    required this.status,
    this.lightingScore,
    this.readings,
    this.notes,
    this.recordId,
    this.reason,
  });

  factory LabAnalysisResponse.fromJson(Map<String, dynamic> json) {
    return LabAnalysisResponse(
      status: json['status'] ?? 'ERROR',
      lightingScore: json['lighting_score'],
      readings: json['readings'] != null ? LabReading.fromJson(json['readings']) : null,
      notes: json['notes'],
      recordId: json['record_id'],
      reason: json['reason'],
    );
  }
}
