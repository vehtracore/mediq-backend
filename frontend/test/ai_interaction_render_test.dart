import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mediq_app/src/features/chat/data/ai_interaction.dart';
import 'package:mediq_app/src/features/chat/presentation/widgets/ai_interaction_bubbles.dart';
import 'package:mediq_app/src/features/chat/presentation/widgets/markdown_bubble.dart';

void main() {
  final citation = {
    'evidence_id': 'chunk-a',
    'chunk_id': 'chunk-a',
    'source_id': 'source-a',
    'document_version_id': 'version-a',
    'title': 'A long synthetic clinical guidance title for mobile displays',
    'issuing_organization': 'Synthetic Clinical Organization',
    'jurisdiction': 'NG',
    'edition': '2026',
    'publication_date': '2026-01-01',
    'section': 'Evaluation',
    'page_start': 2,
    'canonical_url': 'https://example.org/guidance',
  };

  test('message resolves only returned source metadata', () {
    final response = AiInteractionResponse.fromJson({
      'request_id': 'request-a',
      'interaction_id': 'interaction-a',
      'operation_status': 'SUCCEEDED',
      'mode': 'CONVERSATION',
      'result_kind': 'MESSAGE',
      'result': {
        'kind': 'MESSAGE',
        'text': 'Clinical review may help.',
        'evidence_ids': ['chunk-a'],
      },
      'evidence_items': [citation],
    });
    final result = response.result as AiMessageResult;
    expect(result.sources.single.canonicalUrl.toString(),
        'https://example.org/guidance');
    expect(result.visibleText, isNot(contains('chunk-a')));
    expect(
        () => AiInteractionResponse.fromJson({
              'request_id': 'request-a',
              'interaction_id': 'interaction-a',
              'operation_status': 'SUCCEEDED',
              'mode': 'CONVERSATION',
              'result_kind': 'MESSAGE',
              'result': {
                'kind': 'MESSAGE',
                'text': 'Answer',
                'evidence_ids': ['invented'],
              },
              'evidence_items': [citation],
            }),
        throwsFormatException);
    expect(
        () => AiEvidenceSource.fromJson(
            {...citation, 'canonical_url': 'http://unsafe.example'}),
        throwsFormatException);
  });

  testWidgets('sources expand accessibly and open only canonical link',
      (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    Uri? opened;
    final source = AiEvidenceSource.fromJson(citation);
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: AiSourcesSection(
          sources: [source],
          openLink: (url) async {
            opened = url;
            return true;
          },
        ),
      ),
    ));
    expect(find.text('Sources'), findsOneWidget);
    await tester.tap(find.text('Sources'));
    await tester.pumpAndSettle();
    expect(find.text(source.title), findsOneWidget);
    expect(
        find.textContaining('Synthetic Clinical Organization'), findsOneWidget);
    expect(find.text('chunk-a'), findsNothing);
    await tester.tap(find.text('Open source'));
    expect(opened.toString(), 'https://example.org/guidance');
    expect(tester.takeException(), isNull);
  });

  testWidgets('sources omitted when no references', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(body: AiSourcesSection(sources: [])),
    ));
    expect(find.text('Sources'), findsNothing);
  });

  testWidgets('uncertainty-only assessment accepts and hides empty sections',
      (tester) async {
    final result = AiAssessmentResult.fromJson({
      'what_you_told': ['A reported symptom'],
      'possible_explanations': [],
      'why_considered': [],
      'important_negatives': [],
      'next_steps': [],
      'urgent_help_if': [],
      'limitations': 'The cause is not established by the available evidence.',
      'evidence_ids': [],
    });
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: AiAssessmentResultBubble(result: result)),
    ));
    expect(find.text('Limitations and uncertainty'), findsOneWidget);
    for (final section in [
      'Possible explanations',
      'Why these were considered',
      'What to do next',
      'Get urgent help if',
      'Sources',
    ]) {
      expect(find.text(section), findsNothing);
      expect(result.visibleText, isNot(contains(section)));
    }
    expect(tester.takeException(), isNull);
  });

  testWidgets('assessment result shows validated Sources', (tester) async {
    final source = AiEvidenceSource.fromJson(citation);
    final result = AiAssessmentResult(
      whatYouTold: const ['Reported fever'],
      possibleExplanations: const [
        AiAssessmentExplanation('A possible cause', ['fact-a'])
      ],
      whyConsidered: const ['Reported symptoms'],
      importantNegatives: const [],
      nextSteps: const ['Clinical review'],
      urgentHelpIf: const ['Symptoms worsen'],
      limitations: 'This is not a diagnosis.',
      sources: [source],
    );
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: SingleChildScrollView(
            child: AiAssessmentResultBubble(result: result)),
      ),
    ));
    await tester.ensureVisible(find.text('Sources'));
    expect(find.text('Sources'), findsOneWidget);
    expect(find.text('chunk-a'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('message result remains Markdown-capable', (tester) async {
    const result = AiMessageResult('**Protein** can appear in urine.');
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: MarkdownBubble(data: result.text, isMe: false, isDark: false),
      ),
    ));
    expect(find.textContaining('Protein'), findsOneWidget);
  });

  testWidgets('assessment question renders one question and cancel action',
      (tester) async {
    var cancelled = false;
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: AiAssessmentQuestionBubble(
          result: const AiAssessmentQuestionResult(
              'When did you first notice the change?', true),
          canCancel: true,
          onCancel: () => cancelled = true,
        ),
      ),
    ));
    expect(find.text('When did you first notice the change?'), findsOneWidget);
    await tester.tap(find.text('End this assessment'));
    expect(cancelled, isTrue);
  });

  testWidgets('urgent result renders action first and opens Nigerian call',
      (tester) async {
    Uri? called;
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: AiUrgentBubble(
          result: const AiUrgentResult(
            'Call 112 now or go to the nearest emergency department.',
            'These symptoms may need immediate medical care.',
            '112',
          ),
          openCall: (uri) async {
            called = uri;
            return true;
          },
        ),
      ),
    ));
    expect(find.textContaining('Call 112 now'), findsOneWidget);
    expect(find.textContaining('These symptoms'), findsOneWidget);
    await tester.tap(find.text('Call 112'));
    expect(called.toString(), 'tel:112');
  });

  testWidgets('assessment result renders all clinical sections on mobile',
      (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    const result = AiAssessmentResult(
      whatYouTold: ['Foamy urine for three months'],
      possibleExplanations: [
        AiAssessmentExplanation('Several possible causes', ['f1'])
      ],
      whyConsidered: ['The reported duration matters.'],
      importantNegatives: ['No fever was reported.'],
      nextSteps: ['Arrange a clinical review.'],
      urgentHelpIf: ['You develop severe symptoms.'],
      limitations: 'An examination is needed.',
    );
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(
          body: SingleChildScrollView(
        child: AiAssessmentResultBubble(result: result),
      )),
    ));
    expect(find.text('What you told MDQ+'), findsOneWidget);
    expect(find.text('Possible explanations'), findsOneWidget);
    expect(find.text('Why these were considered'), findsOneWidget);
    expect(find.text('Important things your answers do not currently suggest'),
        findsOneWidget);
    expect(find.text('What to do next'), findsOneWidget);
    expect(find.text('Get urgent help if'), findsOneWidget);
    expect(find.text('Limitations and uncertainty'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
