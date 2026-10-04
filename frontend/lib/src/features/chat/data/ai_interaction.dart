enum AiInteractionMode { conversation, assessment, urgent }

class AiEvidenceSource {
  final String id;
  final String title;
  final String organization;
  final String edition;
  final String? section;
  final int? page;
  final String? publicationDate;
  final Uri? canonicalUrl;

  const AiEvidenceSource({
    required this.id,
    required this.title,
    required this.organization,
    required this.edition,
    this.section,
    this.page,
    this.publicationDate,
    this.canonicalUrl,
  });

  factory AiEvidenceSource.fromJson(Map<String, dynamic> data) {
    final rawUrl = data['canonical_url'] as String?;
    final url = rawUrl == null ? null : Uri.tryParse(rawUrl);
    if (rawUrl != null &&
        (url == null ||
            url.scheme != 'https' ||
            url.host.isEmpty ||
            url.userInfo.isNotEmpty ||
            url.hasFragment)) {
      throw const FormatException('Invalid source link.');
    }
    return AiEvidenceSource(
      id: data['evidence_id'] as String,
      title: data['title'] as String,
      organization: data['issuing_organization'] as String,
      edition: data['edition'] as String,
      section: data['section'] as String?,
      page: data['page_start'] as int?,
      publicationDate: data['publication_date'] as String?,
      canonicalUrl: url,
    );
  }
}

List<AiEvidenceSource> _resolveEvidence(
    dynamic rawIds, List<AiEvidenceSource> available) {
  final ids = List<String>.from(rawIds as List? ?? const []);
  if (ids.toSet().length != ids.length) {
    throw const FormatException('Duplicate source reference.');
  }
  final byId = {for (final source in available) source.id: source};
  if (ids.any((id) => !byId.containsKey(id))) {
    throw const FormatException('Unknown source reference.');
  }
  return [for (final id in ids) byId[id]!];
}

sealed class AiInteractionResult {
  const AiInteractionResult();

  String get visibleText;
}

final class AiMessageResult extends AiInteractionResult {
  final String text;
  final List<AiEvidenceSource> sources;
  const AiMessageResult(this.text, [this.sources = const []]);

  @override
  String get visibleText => text;
}

final class AiAssessmentQuestionResult extends AiInteractionResult {
  final String question;
  final bool canCancel;
  const AiAssessmentQuestionResult(this.question, this.canCancel);

  @override
  String get visibleText => question;
}

final class AiAssessmentExplanation {
  final String text;
  final List<String> factIds;
  const AiAssessmentExplanation(this.text, this.factIds);
}

final class AiAssessmentResult extends AiInteractionResult {
  final List<String> whatYouTold;
  final List<AiAssessmentExplanation> possibleExplanations;
  final List<String> whyConsidered;
  final List<String> importantNegatives;
  final List<String> nextSteps;
  final List<String> urgentHelpIf;
  final String limitations;
  final List<AiEvidenceSource> sources;

  const AiAssessmentResult({
    required this.whatYouTold,
    required this.possibleExplanations,
    required this.whyConsidered,
    required this.importantNegatives,
    required this.nextSteps,
    required this.urgentHelpIf,
    required this.limitations,
    this.sources = const [],
  });

  static AiAssessmentResult fromJson(Map<String, dynamic> data,
      [List<AiEvidenceSource> available = const []]) {
    final sources = _resolveEvidence(data['evidence_ids'], available);
    final explanations = (data['possible_explanations'] as List)
        .map((item) => AiAssessmentExplanation(
              item['text'] as String,
              List<String>.from(item['fact_ids'] as List),
            ))
        .toList();
    final result = AiAssessmentResult(
      whatYouTold: List<String>.from(data['what_you_told'] as List),
      possibleExplanations: explanations,
      whyConsidered: List<String>.from(data['why_considered'] as List),
      importantNegatives:
          List<String>.from(data['important_negatives'] as List),
      nextSteps: List<String>.from(data['next_steps'] as List),
      urgentHelpIf: List<String>.from(data['urgent_help_if'] as List),
      limitations: data['limitations'] as String,
      sources: sources,
    );
    if (result.whatYouTold.isEmpty ||
        (explanations.isEmpty &&
            result.nextSteps.isEmpty &&
            result.urgentHelpIf.isEmpty &&
            result.limitations.trim().isEmpty)) {
      throw const FormatException('Incomplete assessment result.');
    }
    return result;
  }

  @override
  String get visibleText {
    String section(String title, List<String> items) =>
        '$title\n${items.map((item) => '- $item').join('\n')}';
    return [
      section('What you told MDQ+', whatYouTold),
      if (possibleExplanations.isNotEmpty)
        section('Possible explanations',
            possibleExplanations.map((e) => e.text).toList()),
      if (whyConsidered.isNotEmpty)
        section('Why these were considered', whyConsidered),
      if (importantNegatives.isNotEmpty)
        section('Important things your answers do not currently suggest',
            importantNegatives),
      if (nextSteps.isNotEmpty) section('What to do next', nextSteps),
      if (urgentHelpIf.isNotEmpty) section('Get urgent help if', urgentHelpIf),
      if (limitations.trim().isNotEmpty)
        'Limitations and uncertainty\n$limitations',
    ].join('\n\n');
  }
}

final class AiUrgentResult extends AiInteractionResult {
  final String action;
  final String reason;
  final String emergencyNumber;
  const AiUrgentResult(this.action, this.reason, this.emergencyNumber);

  @override
  String get visibleText => '$action\n$reason';
}

class AiInteractionResponse {
  final String requestId;
  final String interactionId;
  final String? assessmentId;
  final int? stateVersion;
  final AiInteractionMode mode;
  final AiInteractionResult result;
  final String? usageNotice;
  final String? memorySummary;

  const AiInteractionResponse({
    required this.requestId,
    required this.interactionId,
    this.assessmentId,
    this.stateVersion,
    required this.mode,
    required this.result,
    this.usageNotice,
    this.memorySummary,
  });

  factory AiInteractionResponse.fromJson(Map<String, dynamic> json) {
    if (json['operation_status'] != 'SUCCEEDED') {
      throw const FormatException('Interaction has not completed.');
    }
    final result = Map<String, dynamic>.from(json['result'] as Map);
    final available = (json['evidence_items'] as List? ?? const [])
        .map((item) =>
            AiEvidenceSource.fromJson(Map<String, dynamic>.from(item as Map)))
        .toList();
    final kind = json['result_kind'];
    if (result['kind'] != kind) {
      throw const FormatException('Interaction result mismatch.');
    }
    final AiInteractionResult parsed;
    final AiInteractionMode mode;
    switch (kind) {
      case 'MESSAGE':
        mode = AiInteractionMode.conversation;
        parsed = AiMessageResult(result['text'] as String,
            _resolveEvidence(result['evidence_ids'], available));
      case 'ASSESSMENT_QUESTION':
        mode = AiInteractionMode.assessment;
        parsed = AiAssessmentQuestionResult(
          result['question'] as String,
          result['can_cancel'] == true,
        );
      case 'ASSESSMENT_RESULT':
        mode = AiInteractionMode.assessment;
        parsed = AiAssessmentResult.fromJson(result, available);
      case 'URGENT':
        mode = AiInteractionMode.urgent;
        parsed = AiUrgentResult(
          result['action'] as String,
          result['reason'] as String,
          result['emergency_number'] as String,
        );
      default:
        throw const FormatException('Unsupported interaction result.');
    }
    if (json['mode'] != mode.name.toUpperCase() ||
        (parsed.visibleText).trim().isEmpty) {
      throw const FormatException('Invalid interaction response.');
    }
    return AiInteractionResponse(
      requestId: json['request_id'] as String,
      interactionId: json['interaction_id'] as String,
      assessmentId: json['assessment_id'] as String?,
      stateVersion: json['state_version'] as int?,
      mode: mode,
      result: parsed,
      usageNotice: json['usage_notice'] as String?,
      memorySummary: json['memory_summary'] as String?,
    );
  }
}
