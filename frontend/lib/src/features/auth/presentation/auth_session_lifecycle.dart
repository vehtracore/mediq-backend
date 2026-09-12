import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../../../core/services/notification_service.dart';
import '../../chat/presentation/ai_chat_controller.dart';
import '../../chat/presentation/consultation_session_controller.dart';
import '../../notifications/data/notification_repository.dart';
import '../../notifications/navigation/notification_navigation_coordinator.dart';
import '../../vault/data/vault_repository.dart';
import '../data/auth_state_provider.dart';
import '../data/shell_identity.dart';
import 'user_controller.dart';

class SessionUserTransitionTracker {
  String? _previousUserId;

  String? observe(AuthChangeEvent event, String? nextUserId) {
    if (event == AuthChangeEvent.signedOut) {
      final userToClear = _previousUserId;
      _previousUserId = null;
      return userToClear;
    }

    if (_previousUserId != null &&
        nextUserId != null &&
        _previousUserId != nextUserId) {
      final userToClear = _previousUserId;
      _previousUserId = nextUserId;
      return userToClear;
    }

    _previousUserId = nextUserId ?? _previousUserId;
    return null;
  }
}

Future<void> clearAuthenticatedUserState(Ref ref, String? userId) async {
  await ref.read(consultationSessionRegistryProvider).shutdownAll();
  try {
    await clearShellIdentityForUser(
      ref.read(shellIdentityStoreProvider),
      userId,
    );
  } catch (_) {
    // In-memory user state must still be removed if local storage is unhealthy.
  }
  ref.read(userControllerProvider.notifier).logout();
  ref.invalidate(activeShellIdentityProvider);
  ref.invalidate(userProvider);
  ref.invalidate(vaultHistoryProvider);
  ref.invalidate(aiChatControllerProvider);
  ref.invalidate(consultationSessionProvider);
  ref.invalidate(consultationSessionRegistryProvider);
  ref.invalidate(notificationsProvider);
  ref.invalidate(unreadNotificationCountProvider);
}

/// App-scoped bridge from Supabase session events to user-owned Riverpod state.
final authSessionLifecycleProvider = Provider<void>((ref) {
  final tracker = SessionUserTransitionTracker();

  ref.listen<AsyncValue<AuthState>>(
    supabaseAuthProvider,
    (_, next) {
      next.whenData((state) {
        final nextUserId = state.session?.user.id;
        final userToClear = tracker.observe(state.event, nextUserId);

        if (state.event == AuthChangeEvent.signedOut) {
          unawaited(
            ref.read(notificationServiceProvider).handleTerminalSignOut(),
          );
          ref.read(notificationNavigationCoordinatorProvider).clear();
          unawaited(clearAuthenticatedUserState(ref, userToClear));
          return;
        }

        if (userToClear != null) {
          unawaited(
            ref.read(notificationServiceProvider).handleTerminalSignOut(),
          );
          ref.read(notificationNavigationCoordinatorProvider).clear();
          unawaited(clearAuthenticatedUserState(ref, userToClear));
          return;
        }

        if (state.event == AuthChangeEvent.initialSession ||
            state.event == AuthChangeEvent.signedIn ||
            state.event == AuthChangeEvent.tokenRefreshed ||
            state.event == AuthChangeEvent.userUpdated) {
          // Cold start, refresh, and user updates are recovery points for a
          // profile request that previously failed transiently.
          ref.invalidate(userProvider);
        }
      });
    },
    fireImmediately: true,
  );
});
