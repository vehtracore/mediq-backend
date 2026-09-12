import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'auth_state_provider.dart';
import 'user_model.dart';

class ShellIdentity {
  const ShellIdentity({
    required this.userId,
    required this.displayName,
    required this.role,
    this.avatarUrl = '',
  });

  final String userId;
  final String displayName;
  final String role;
  final String avatarUrl;

  factory ShellIdentity.fromUser(String supabaseUserId, User user) {
    return ShellIdentity(
      userId: supabaseUserId,
      displayName: '${user.firstName} ${user.lastName}'.trim(),
      role: user.role,
      avatarUrl: user.imageUrl,
    );
  }

  Map<String, dynamic> toJson() => {
        'user_id': userId,
        'display_name': displayName,
        'role': role,
        'avatar_url': avatarUrl,
      };

  static ShellIdentity? fromJson(Map<String, dynamic> json) {
    final userId = json['user_id'];
    final displayName = json['display_name'];
    final role = json['role'];
    if (userId is! String ||
        displayName is! String ||
        role is! String ||
        userId.isEmpty ||
        displayName.trim().isEmpty ||
        !_isKnownRole(role)) {
      return null;
    }
    return ShellIdentity(
      userId: userId,
      displayName: displayName,
      role: role,
      avatarUrl:
          json['avatar_url'] is String ? json['avatar_url'] as String : '',
    );
  }

  static bool _isKnownRole(String role) =>
      role == 'patient' || role == 'doctor' || role == 'admin';
}

abstract class ShellIdentityStore {
  Future<ShellIdentity?> read(String userId);

  Future<void> write(ShellIdentity identity);

  Future<void> remove(String userId);
}

Future<void> clearShellIdentityForUser(
  ShellIdentityStore store,
  String? userId,
) async {
  if (userId != null) await store.remove(userId);
}

class SharedPreferencesShellIdentityStore implements ShellIdentityStore {
  static const _keyPrefix = 'mdq_shell_identity_v1_';

  String _key(String userId) => '$_keyPrefix$userId';

  @override
  Future<ShellIdentity?> read(String userId) async {
    final prefs = await SharedPreferences.getInstance();
    final value = prefs.getString(_key(userId));
    if (value == null) return null;
    try {
      final decoded = jsonDecode(value);
      if (decoded is! Map<String, dynamic>) return null;
      final identity = ShellIdentity.fromJson(decoded);
      return identity?.userId == userId ? identity : null;
    } catch (_) {
      return null;
    }
  }

  @override
  Future<void> write(ShellIdentity identity) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_key(identity.userId), jsonEncode(identity.toJson()));
  }

  @override
  Future<void> remove(String userId) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_key(userId));
  }
}

final shellIdentityStoreProvider = Provider<ShellIdentityStore>((ref) {
  return SharedPreferencesShellIdentityStore();
});

final activeShellIdentityProvider = FutureProvider<ShellIdentity?>((ref) async {
  final userId = ref.watch(authUserIdProvider);
  if (userId == null) return null;
  return ref.watch(shellIdentityStoreProvider).read(userId);
});
