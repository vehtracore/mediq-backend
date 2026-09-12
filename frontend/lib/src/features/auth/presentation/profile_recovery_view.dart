import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/profile_exception.dart';
import '../data/shell_identity.dart';
import 'user_controller.dart';

class AuthenticatedProfileRecoveryView extends ConsumerWidget {
  const AuthenticatedProfileRecoveryView({
    super.key,
    this.error,
    this.compact = false,
    this.onRetry,
  });

  final Object? error;
  final bool compact;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final shell = ref.watch(activeShellIdentityProvider).valueOrNull;
    final theme = Theme.of(context);
    final isLoading = error == null;
    final title = shell?.displayName.trim().isNotEmpty == true
        ? shell!.displayName
        : isLoading
            ? 'Restoring your profile'
            : 'Profile temporarily unavailable';
    final message = switch (error) {
      ProfileAuthoritativeException() =>
        'Your secure session is active, but your MDQ+ profile could not be verified.',
      ProfileTemporaryException() =>
        'Your secure session is active. Check your connection and try again.',
      _ when !isLoading =>
        'Your secure session is active. Please try loading your profile again.',
      _ => 'Loading your account details…',
    };

    final content = Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        _ShellAvatar(identity: shell, radius: compact ? 22 : 36),
        SizedBox(height: compact ? 8 : 16),
        Text(
          title,
          textAlign: TextAlign.center,
          style: (compact
                  ? theme.textTheme.titleMedium
                  : theme.textTheme.titleLarge)
              ?.copyWith(fontWeight: FontWeight.bold),
        ),
        const SizedBox(height: 8),
        Text(message, textAlign: TextAlign.center),
        const SizedBox(height: 16),
        if (isLoading)
          const CircularProgressIndicator()
        else
          FilledButton.icon(
            onPressed: onRetry ?? () => ref.invalidate(userProvider),
            icon: const Icon(Icons.refresh),
            label: const Text('Retry profile'),
          ),
      ],
    );

    if (compact) return content;
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: content,
      ),
    );
  }
}

class _ShellAvatar extends StatelessWidget {
  const _ShellAvatar({required this.identity, required this.radius});

  final ShellIdentity? identity;
  final double radius;

  @override
  Widget build(BuildContext context) {
    final avatarUrl = identity?.avatarUrl ?? '';
    final initials = _initials(identity?.displayName ?? '');
    return CircleAvatar(
      radius: radius,
      backgroundColor: const Color(0xFF4A90E2),
      child: avatarUrl.isNotEmpty
          ? ClipOval(
              child: Image.network(
                avatarUrl,
                width: radius * 2,
                height: radius * 2,
                fit: BoxFit.cover,
                errorBuilder: (_, __, ___) => Icon(
                  Icons.person_outline,
                  color: Colors.white,
                  size: radius,
                ),
              ),
            )
          : initials.isNotEmpty
              ? Text(
                  initials,
                  style: TextStyle(
                    color: Colors.white,
                    fontWeight: FontWeight.bold,
                    fontSize: radius * 0.65,
                  ),
                )
              : const Icon(Icons.person_outline, color: Colors.white),
    );
  }

  String _initials(String name) {
    final parts = name
        .trim()
        .split(RegExp(r'\s+'))
        .where((part) => part.isNotEmpty)
        .toList();
    if (parts.isEmpty) return '';
    return parts.take(2).map((part) => part[0].toUpperCase()).join();
  }
}
