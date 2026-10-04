import 'package:flutter/material.dart';
import 'package:mediq_app/src/features/chat/data/ai_interaction.dart';
import 'package:url_launcher/url_launcher.dart';

class AiSourcesSection extends StatelessWidget {
  final List<AiEvidenceSource> sources;
  final Future<bool> Function(Uri)? openLink;

  const AiSourcesSection({super.key, required this.sources, this.openLink});

  @override
  Widget build(BuildContext context) {
    if (sources.isEmpty) return const SizedBox.shrink();
    final theme = Theme.of(context);
    return ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 680),
      child: Semantics(
        label: 'Sources, ${sources.length} clinical references',
        child: ExpansionTile(
          tilePadding: EdgeInsets.zero,
          title: Text('Sources', style: theme.textTheme.titleSmall),
          children: [
            for (final source in sources)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(source.title,
                        style: theme.textTheme.bodyMedium
                            ?.copyWith(fontWeight: FontWeight.w600)),
                    Text(
                        [
                          source.organization,
                          if (source.section != null) source.section!,
                          if (source.page != null) 'p. ${source.page}',
                          if (source.publicationDate != null)
                            source.publicationDate!,
                        ].join(' / '),
                        style: theme.textTheme.bodySmall),
                    if (source.canonicalUrl != null)
                      TextButton.icon(
                        onPressed: () =>
                            (openLink ?? launchUrl)(source.canonicalUrl!),
                        icon: const Icon(Icons.open_in_new, size: 16),
                        label: const Text('Open source'),
                      ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class AiAssessmentQuestionBubble extends StatelessWidget {
  final AiAssessmentQuestionResult result;
  final bool canCancel;
  final VoidCallback onCancel;

  const AiAssessmentQuestionBubble({
    super.key,
    required this.result,
    required this.canCancel,
    required this.onCancel,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Align(
      alignment: Alignment.centerLeft,
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxWidth: MediaQuery.of(context).size.width * 0.84,
        ),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 8),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(result.question, style: theme.textTheme.bodyLarge),
              if (canCancel && result.canCancel)
                TextButton.icon(
                  onPressed: onCancel,
                  icon: const Icon(Icons.close, size: 18),
                  label: const Text('End this assessment'),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class AiAssessmentResultBubble extends StatelessWidget {
  final AiAssessmentResult result;

  const AiAssessmentResultBubble({super.key, required this.result});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    Widget section(String title, List<String> lines) => Padding(
          padding: const EdgeInsets.only(bottom: 18),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title,
                  style: theme.textTheme.titleSmall?.copyWith(
                    fontWeight: FontWeight.w700,
                  )),
              const SizedBox(height: 6),
              for (final line in lines)
                Padding(
                  padding: const EdgeInsets.only(bottom: 5),
                  child: Text(line, style: theme.textTheme.bodyMedium),
                ),
            ],
          ),
        );

    return Semantics(
      label: result.visibleText,
      child: Align(
        alignment: Alignment.centerLeft,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 680),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 4),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                section('What you told MDQ+', result.whatYouTold),
                if (result.possibleExplanations.isNotEmpty)
                  section('Possible explanations',
                      result.possibleExplanations.map((e) => e.text).toList()),
                if (result.whyConsidered.isNotEmpty)
                  section('Why these were considered', result.whyConsidered),
                if (result.importantNegatives.isNotEmpty)
                  section(
                      'Important things your answers do not currently suggest',
                      result.importantNegatives),
                if (result.nextSteps.isNotEmpty)
                  section('What to do next', result.nextSteps),
                if (result.urgentHelpIf.isNotEmpty)
                  section('Get urgent help if', result.urgentHelpIf),
                if (result.limitations.trim().isNotEmpty)
                  section('Limitations and uncertainty', [result.limitations]),
                AiSourcesSection(sources: result.sources),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class AiUrgentBubble extends StatelessWidget {
  final AiUrgentResult result;
  final Future<bool> Function(Uri)? openCall;

  const AiUrgentBubble({super.key, required this.result, this.openCall});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Semantics(
      liveRegion: true,
      label: 'Urgent medical guidance. ${result.action} ${result.reason}',
      child: Align(
        alignment: Alignment.centerLeft,
        child: Container(
          margin: const EdgeInsets.symmetric(vertical: 8),
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: theme.colorScheme.errorContainer,
            border: Border.all(color: theme.colorScheme.error),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(Icons.warning_amber_rounded,
                  color: theme.colorScheme.onErrorContainer),
              const SizedBox(height: 8),
              Text(result.action,
                  style: theme.textTheme.titleMedium?.copyWith(
                    color: theme.colorScheme.onErrorContainer,
                    fontWeight: FontWeight.bold,
                  )),
              const SizedBox(height: 6),
              Text(result.reason,
                  style: TextStyle(color: theme.colorScheme.onErrorContainer)),
              const SizedBox(height: 8),
              FilledButton.icon(
                onPressed: () => (openCall ?? launchUrl)(
                    Uri(scheme: 'tel', path: result.emergencyNumber)),
                icon: const Icon(Icons.call),
                label: Text('Call ${result.emergencyNumber}'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
