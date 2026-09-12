import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../../../presentation/widgets/global_error_widget.dart';
import '../../../shared/presentation/widgets/skeleton_loader.dart';
import '../data/notification_record.dart';
import '../data/notification_repository.dart';
import '../navigation/notification_navigation_coordinator.dart';

class NotificationsScreen extends ConsumerWidget {
  const NotificationsScreen({super.key});

  Future<void> _refresh(WidgetRef ref) async {
    ref.invalidate(unreadNotificationCountProvider);
    await ref.refresh(notificationsProvider.future).then<void>((_) {});
  }

  Future<void> _markAllRead(WidgetRef ref) async {
    await ref.read(notificationRepositoryProvider).markAllRead();
    ref.invalidate(notificationsProvider);
    ref.invalidate(unreadNotificationCountProvider);
  }

  Future<void> _open(
    WidgetRef ref,
    NotificationRecord notification,
  ) async {
    if (!notification.isRead) {
      try {
        await ref
            .read(notificationRepositoryProvider)
            .markRead(notification.id);
        ref.invalidate(notificationsProvider);
        ref.invalidate(unreadNotificationCountProvider);
      } catch (_) {
        // Read-state sync must not prevent the notification destination opening.
      }
    }
    ref
        .read(notificationNavigationCoordinatorProvider)
        .submit(notification.intentData);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final notifications = ref.watch(notificationsProvider);
    final unread = ref.watch(unreadNotificationCountProvider).valueOrNull ?? 0;
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: Text('Notifications', style: theme.textTheme.titleLarge),
        actions: [
          IconButton(
            tooltip: 'Mark all as read',
            onPressed: unread == 0 ? null : () => _markAllRead(ref),
            icon: const Icon(Icons.done_all_rounded),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () => _refresh(ref),
        child: notifications.when(
          loading: () => ListView.builder(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.all(16),
            itemCount: 6,
            itemBuilder: (_, __) => Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: SkeletonLoader(
                child: Container(
                  height: 88,
                  decoration: BoxDecoration(
                    color: theme.cardTheme.color,
                    borderRadius: BorderRadius.circular(8),
                  ),
                ),
              ),
            ),
          ),
          error: (error, _) => ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            children: [
              SizedBox(
                height: MediaQuery.sizeOf(context).height * 0.7,
                child: GlobalErrorWidget(
                  error: error,
                  onRetry: () => ref.invalidate(notificationsProvider),
                ),
              ),
            ],
          ),
          data: (items) {
            if (items.isEmpty) {
              return ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                children: [
                  SizedBox(
                    height: MediaQuery.sizeOf(context).height * 0.7,
                    child: const Center(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Icons.notifications_none_rounded, size: 52),
                          SizedBox(height: 12),
                          Text('No notifications yet'),
                        ],
                      ),
                    ),
                  ),
                ],
              );
            }
            return ListView.separated(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.all(16),
              itemCount: items.length,
              separatorBuilder: (_, __) => const SizedBox(height: 8),
              itemBuilder: (_, index) => _NotificationTile(
                notification: items[index],
                onTap: () => _open(ref, items[index]),
              ),
            );
          },
        ),
      ),
    );
  }
}

class _NotificationTile extends StatelessWidget {
  const _NotificationTile({
    required this.notification,
    required this.onTap,
  });

  final NotificationRecord notification;
  final VoidCallback onTap;

  IconData get _icon {
    final type = notification.type ?? '';
    if (type.startsWith('consultation') || type == 'prescription_added') {
      return Icons.medical_services_outlined;
    }
    if (type.startsWith('subscription')) {
      return Icons.workspace_premium_outlined;
    }
    if (type.startsWith('family')) return Icons.group_outlined;
    if (type == 'payout_sent') return Icons.account_balance_wallet_outlined;
    if (type == 'referral_created') return Icons.assignment_outlined;
    return Icons.notifications_outlined;
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final accent = notification.isRead
        ? theme.colorScheme.outline
        : theme.colorScheme.primary;
    return Material(
      color: notification.isRead
          ? theme.cardTheme.color
          : theme.colorScheme.primaryContainer.withValues(alpha: 0.22),
      borderRadius: BorderRadius.circular(8),
      child: InkWell(
        borderRadius: BorderRadius.circular(8),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SizedBox(
                width: 36,
                height: 36,
                child: Icon(_icon, color: accent, size: 22),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            notification.title,
                            style: theme.textTheme.titleSmall?.copyWith(
                              fontWeight: notification.isRead
                                  ? FontWeight.w500
                                  : FontWeight.w700,
                            ),
                          ),
                        ),
                        const SizedBox(width: 8),
                        Text(
                          DateFormat('MMM d, h:mm a')
                              .format(notification.createdAt),
                          style: theme.textTheme.bodySmall,
                        ),
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(notification.body, style: theme.textTheme.bodyMedium),
                  ],
                ),
              ),
              if (!notification.isRead) ...[
                const SizedBox(width: 8),
                Container(
                  width: 7,
                  height: 7,
                  decoration: BoxDecoration(
                    color: theme.colorScheme.primary,
                    shape: BoxShape.circle,
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
