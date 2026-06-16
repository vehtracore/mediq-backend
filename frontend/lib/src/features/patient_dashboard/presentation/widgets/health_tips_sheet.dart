import 'dart:ui';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/features/content/data/content_repository.dart';
import 'package:url_launcher/url_launcher.dart';

final healthTipsProvider = FutureProvider.autoDispose((ref) async {
  return await ref.watch(contentRepositoryProvider).getHealthTips();
});

class HealthTipsSheet extends ConsumerWidget {
  final DraggableScrollableController controller;

  const HealthTipsSheet({super.key, required this.controller});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tipsAsync = ref.watch(healthTipsProvider);
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;

    return DraggableScrollableSheet(
      controller: controller,
      initialChildSize: 0.1, // Show just the tip
      minChildSize: 0.1,
      maxChildSize: 0.85,
      snap: true,
      builder: (context, scrollController) {
        return ClipRRect(
          borderRadius: const BorderRadius.vertical(top: Radius.circular(32)),
          child: BackdropFilter(
            filter: ImageFilter.blur(sigmaX: 10, sigmaY: 10),
            child: Container(
              decoration: BoxDecoration(
                // ✅ Dynamic Sheet Color
                color: isDark
                    ? const Color(0xFF1E1E1E).withOpacity(0.95)
                    : Colors.white.withOpacity(0.95),
                borderRadius:
                    const BorderRadius.vertical(top: Radius.circular(32)),
                boxShadow: [
                  BoxShadow(
                      color: Colors.black.withOpacity(0.1),
                      blurRadius: 20,
                      offset: const Offset(0, -5))
                ],
              ),
              child: tipsAsync.when(
                loading: () => const Center(child: CircularProgressIndicator()),
                error: (e, s) => Center(
                    child: Text("Failed to load tips",
                        style: theme.textTheme.bodyMedium)),
                data: (tips) => ListView.builder(
                  controller: scrollController,
                  padding: const EdgeInsets.all(24),
                  itemCount: tips.isEmpty ? 2 : tips.length + 1,
                  itemBuilder: (context, index) {
                    if (index == 0) {
                      return Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Center(
                              child: Container(
                                  width: 40,
                                  height: 4,
                                  decoration: BoxDecoration(
                                      color: Colors.grey[300],
                                      borderRadius: BorderRadius.circular(2)))),
                          const SizedBox(height: 24),
                          Text("Daily Health Tips",
                              style: theme.textTheme.headlineSmall?.copyWith(
                                  fontWeight: FontWeight.bold)), // ✅ Dynamic
                          const SizedBox(height: 16),
                        ],
                      );
                    }
                    if (tips.isEmpty) {
                      return Center(
                        child: Padding(
                          padding: const EdgeInsets.only(top: 40),
                          child: Text("No health tips available.",
                              style: theme.textTheme.bodyMedium),
                        ),
                      );
                    }
                    final tip = tips[index - 1];
                    return _TipCard(tip: tip);
                  },
                ),
              ),
            ),
          ),
        );
      },
    );
  }
}

class _TipCard extends StatelessWidget {
  final HealthTip tip;
  const _TipCard({required this.tip});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;
    final rawImageUrl = tip.imageUrl?.trim();
    final imageUrl =
        rawImageUrl == null || rawImageUrl.isEmpty ? null : rawImageUrl;
    final hasValidUrl = imageUrl != null && imageUrl.startsWith('http');

    return Container(
      margin: const EdgeInsets.only(bottom: 16),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: isDark
            ? const Color(0xFF2C2C2C)
            : Colors.grey[50], // ✅ Dynamic Card
        borderRadius: BorderRadius.circular(20),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Container(
                      padding:
                          const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                      decoration: BoxDecoration(
                          color: const Color(0xFF4A90E2).withOpacity(0.1),
                          borderRadius: BorderRadius.circular(8)),
                      child: Text(tip.category.toUpperCase(),
                          style: const TextStyle(
                              fontSize: 10,
                              fontWeight: FontWeight.bold,
                              color: Color(0xFF4A90E2))),
                    ),
                    const SizedBox(height: 8),
                    Text(tip.title,
                        style: theme.textTheme.titleMedium
                            ?.copyWith(fontWeight: FontWeight.bold)), // ✅ Dynamic
                    const SizedBox(height: 4),
                    Text(tip.readTime,
                        style: TextStyle(fontSize: 12, color: Colors.grey[500])),
                  ],
                ),
              ),
            ],
          ),
          if (hasValidUrl) ...[
            const SizedBox(height: 16),
            ClipRRect(
              borderRadius: BorderRadius.circular(12),
              child: Image.network(
                imageUrl!,
                width: double.infinity,
                height: 150,
                fit: BoxFit.cover,
                errorBuilder: (context, error, stackTrace) => const SizedBox(),
              ),
            ),
          ],
          if (tip.content.isNotEmpty) ...[
            const SizedBox(height: 16),
            Text(tip.content, style: theme.textTheme.bodyMedium),
          ],
          if (tip.externalLink != null && tip.externalLink!.isNotEmpty) ...[
            const SizedBox(height: 12),
            OutlinedButton.icon(
              onPressed: () async {
                final url = Uri.tryParse(tip.externalLink!);
                if (url != null) {
                  try {
                    await launchUrl(url, mode: LaunchMode.externalApplication);
                  } catch (e) {
                    debugPrint('Could not launch $url');
                  }
                }
              },
              icon: const Icon(Icons.open_in_new, size: 18),
              label: const Text("Read More"),
              style: OutlinedButton.styleFrom(
                foregroundColor: const Color(0xFF4A90E2),
                side: const BorderSide(color: Color(0xFF4A90E2)),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(8),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}
