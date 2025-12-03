import 'dart:ui';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/features/content/data/content_repository.dart';

final healthTipsProvider = FutureProvider.autoDispose((ref) async {
  return await ref.watch(contentRepositoryProvider).getHealthTips();
});

class HealthTipsSheet extends ConsumerWidget {
  final DraggableScrollableController controller;

  const HealthTipsSheet({super.key, required this.controller});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tipsAsync = ref.watch(healthTipsProvider);

    return DraggableScrollableSheet(
      controller: controller,
      initialChildSize: 0.3,
      minChildSize: 0.15,
      maxChildSize: 1.0,
      snap: true,
      builder: (context, scrollController) {
        // <--- THIS CONTROLLER
        return ClipRRect(
          borderRadius: const BorderRadius.vertical(top: Radius.circular(32)),
          child: BackdropFilter(
            filter: ImageFilter.blur(sigmaX: 10, sigmaY: 10),
            child: Container(
              decoration: BoxDecoration(
                color: Colors.white.withOpacity(0.9),
                borderRadius: const BorderRadius.vertical(
                  top: Radius.circular(32),
                ),
                border: Border(
                  top: BorderSide(
                    color: Colors.white.withOpacity(0.5),
                    width: 1,
                  ),
                ),
                boxShadow: [
                  BoxShadow(
                    color: Colors.black.withOpacity(0.05),
                    blurRadius: 20,
                    spreadRadius: 5,
                  ),
                ],
              ),
              child: Column(
                children: [
                  Center(
                    child: Container(
                      margin: const EdgeInsets.symmetric(vertical: 12),
                      width: 40,
                      height: 4,
                      decoration: BoxDecoration(
                        color: Colors.grey[300],
                        borderRadius: BorderRadius.circular(10),
                      ),
                    ),
                  ),
                  Padding(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 24,
                      vertical: 8,
                    ),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        const Text(
                          "Health Insights",
                          style: TextStyle(
                            fontSize: 20,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                        IconButton(
                          icon: const Icon(
                            Icons.refresh,
                            size: 20,
                            color: Colors.grey,
                          ),
                          onPressed: () => ref.refresh(healthTipsProvider),
                        ),
                      ],
                    ),
                  ),
                  Expanded(
                    child: tipsAsync.when(
                      loading: () =>
                          const Center(child: CircularProgressIndicator()),
                      error: (e, _) =>
                          Center(child: Text("Failed to load tips: $e")),
                      data: (tips) {
                        if (tips.isEmpty)
                          return const Center(
                            child: Text("No health tips yet."),
                          );
                        return ListView.builder(
                          controller:
                              scrollController, // <--- MUST BE HERE TO SCROLL/DRAG
                          padding: const EdgeInsets.symmetric(horizontal: 20),
                          itemCount: tips.length,
                          itemBuilder: (context, index) =>
                              _buildTipCard(tips[index]),
                        );
                      },
                    ),
                  ),
                ],
              ),
            ),
          ),
        );
      },
    );
  }

  Widget _buildTipCard(HealthTip tip) {
    return Container(
      margin: const EdgeInsets.only(bottom: 16),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(20),
        boxShadow: [
          BoxShadow(
            color: Colors.grey.withOpacity(0.05),
            blurRadius: 15,
            offset: const Offset(0, 5),
          ),
        ],
      ),
      child: Row(
        children: [
          Container(
            width: 70,
            height: 70,
            decoration: BoxDecoration(
              color: const Color(0xFF4A90E2).withOpacity(0.15),
              borderRadius: BorderRadius.circular(16),
            ),
            child: tip.imageUrl != null && tip.imageUrl!.isNotEmpty
                ? Image.network(
                    tip.imageUrl!,
                    fit: BoxFit.cover,
                    errorBuilder: (_, __, ___) =>
                        const Icon(Icons.article, color: Color(0xFF4A90E2)),
                  )
                : const Icon(Icons.article, color: Color(0xFF4A90E2), size: 32),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 8,
                    vertical: 4,
                  ),
                  decoration: BoxDecoration(
                    color: const Color(0xFF4A90E2).withOpacity(0.1),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    tip.category.toUpperCase(),
                    style: const TextStyle(
                      fontSize: 10,
                      fontWeight: FontWeight.bold,
                      color: Color(0xFF4A90E2),
                    ),
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  tip.title,
                  style: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.bold,
                    color: Color(0xFF2D3436),
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  tip.readTime,
                  style: TextStyle(fontSize: 12, color: Colors.grey[500]),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
