import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'api_constants.dart';
import '../router/app_router.dart';
import '../storage/storage_service.dart';
import 'package:supabase_flutter/supabase_flutter.dart' hide User;
import 'app_exception.dart';

final dioProvider = Provider<Dio>((ref) {
  final options = BaseOptions(
    baseUrl: ApiConstants.baseUrl,
    connectTimeout: const Duration(seconds: 90),
    receiveTimeout: const Duration(seconds: 90),
    headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
  );

  final dio = Dio(options);
  final storage = ref.read(storageServiceProvider);
  Future<String?>? refreshInFlight;

  bool isSessionExpiring(Session session) {
    final expiresAt = session.expiresAt;
    if (expiresAt == null) return false;

    final expiry = DateTime.fromMillisecondsSinceEpoch(
      expiresAt * 1000,
      isUtc: true,
    );
    return expiry.isBefore(DateTime.now().toUtc().add(const Duration(minutes: 1)));
  }

  Future<void> persistSession(Session session) async {
    await storage.saveToken(session.accessToken);

    final refreshToken = session.refreshToken;
    if (refreshToken != null && refreshToken.isNotEmpty) {
      await storage.saveRefreshToken(refreshToken);
    }
  }

  Future<String?> refreshAccessToken() {
    if (refreshInFlight != null) return refreshInFlight!;

    refreshInFlight = (() async {
      final auth = Supabase.instance.client.auth;
      final refreshToken =
          auth.currentSession?.refreshToken ?? await storage.getRefreshToken();

      if (refreshToken == null || refreshToken.isEmpty) {
        return null;
      }

      final response = await auth.refreshSession(refreshToken);
      final session = response.session ?? auth.currentSession;
      if (session == null) return null;

      await persistSession(session);
      return session.accessToken;
    })();

    return refreshInFlight!.whenComplete(() {
      refreshInFlight = null;
    });
  }

  Future<String?> validAccessToken() async {
    final session = Supabase.instance.client.auth.currentSession;
    if (session == null) return null;

    if (isSessionExpiring(session)) {
      return refreshAccessToken();
    }

    await persistSession(session);
    return session.accessToken;
  }

  Future<void> clearSessionAndRouteToLogin() async {
    try {
      await Supabase.instance.client.auth.signOut();
    } catch (_) {}

    await storage.deleteToken();

    final context = rootNavigatorKey.currentContext;
    if (context != null && context.mounted) {
      GoRouter.of(context).go('/login');
    }
  }

  dio.interceptors.add(
    QueuedInterceptorsWrapper(
      onRequest: (options, handler) async {
        try {
          final token = await validAccessToken();

          if (token != null && token.isNotEmpty) {
            options.headers['Authorization'] = 'Bearer $token';
          } else {
            if (kDebugMode) {
              print('⚠️ [AUTH] -> No Supabase session token found.');
            }
          }

          if (kDebugMode) {
            print('🌐 [REQ] -> ${options.method} ${options.path}');
          }
        } catch (e) {
          if (kDebugMode) print('⚠️ [AUTH ERROR] -> Could not read token: $e');
        }

        return handler.next(options);
      },
      onResponse: (response, handler) {
        if (kDebugMode) {
          print('✅ [RESP] <- ${response.statusCode}');
        }
        return handler.next(response);
      },
      onError: (DioException e, handler) async {
        if (kDebugMode) {
          print('❌ [ERR] -> ${e.message}');
          if (e.response != null) {
            print('📜 [RESP BODY] -> ${e.response?.data}');
          }
        }

        // --- 401 UNAUTHORIZED CHECK: Silent Refresh ---
        if (e.response?.statusCode == 401 &&
            e.requestOptions.extra['authRetry'] != true) {
          if (kDebugMode) {
            print('⚠️ [AUTH] -> 401 Detected. Attempting silent token refresh.');
          }

          try {
            final refreshedToken = await refreshAccessToken();
            if (refreshedToken != null && refreshedToken.isNotEmpty) {
              final retryOptions = e.requestOptions.copyWith(
                headers: {
                  ...e.requestOptions.headers,
                  'Authorization': 'Bearer $refreshedToken',
                },
                extra: {
                  ...e.requestOptions.extra,
                  'authRetry': true,
                },
              );
              final retryResponse = await dio.fetch<dynamic>(retryOptions);
              return handler.resolve(retryResponse);
            }
          } catch (refreshError) {
            if (kDebugMode) {
              print('⚠️ [AUTH] -> Silent refresh failed: $refreshError');
            }
          }

          await clearSessionAndRouteToLogin();
          return handler.next(e);
        }

        // --- SUSPENSION CHECK: 403 with "Account suspended" ---
        if (e.response?.statusCode == 403) {
          final data = e.response?.data;
          final detail = data is Map ? data['detail'] : data?.toString();

          if (detail != null &&
              detail.toString().contains('Account suspended')) {
            if (kDebugMode) {
              print('🚫 [AUTH] -> Account suspended. Logging out...');
            }

            await storage.deleteToken();

            final context = rootNavigatorKey.currentContext;
            if (context != null && context.mounted) {
              showDialog(
                context: context,
                barrierDismissible: false,
                builder: (_) => AlertDialog(
                  title: const Text('Account Suspended'),
                  content: const Text(
                    'Your account has been suspended. Please contact support for assistance.',
                  ),
                  actions: [
                    TextButton(
                      onPressed: () {
                        Navigator.of(context).pop(); // close dialog
                        GoRouter.of(context).go('/login');
                      },
                      child: const Text('Understood'),
                    ),
                  ],
                ),
              );
            }
          }
        }

        String? userFriendlyMessage;
        if (e.type == DioExceptionType.connectionError ||
            e.type == DioExceptionType.connectionTimeout ||
            e.type == DioExceptionType.receiveTimeout) {
          userFriendlyMessage = 'No internet connection. Please check your network and try again.';
        } else if (e.response?.statusCode != null && e.response!.statusCode! >= 500) {
          userFriendlyMessage = 'Our servers are experiencing a hiccup. Please try again in a moment.';
        }

        if (userFriendlyMessage != null) {
          final customError = AppException(userFriendlyMessage, originalException: e);
          return handler.next(
            e.copyWith(
              message: userFriendlyMessage,
              error: customError,
            ),
          );
        }

        return handler.next(e);
      },
    ),
  );

  return dio;
});
