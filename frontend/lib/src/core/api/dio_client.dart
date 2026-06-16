import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'api_constants.dart';
import '../router/app_router.dart';
import '../storage/storage_service.dart';
import 'package:supabase_flutter/supabase_flutter.dart' hide User;
import 'api_error_mapper.dart';
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

  dio.interceptors.add(
    InterceptorsWrapper(
      onRequest: (options, handler) async {
        try {
          final token = Supabase.instance.client.auth.currentSession?.accessToken;

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

        // --- 401 UNAUTHORIZED CHECK ---
        if (e.response?.statusCode == 401) {
          try {
            await Supabase.instance.client.auth.signOut();
          } catch (_) {}

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

        final safeMessage = ApiErrorMapper.getSecureErrorMessage(e);
        final customError = AppException(safeMessage, originalException: e);
        return handler.next(
          e.copyWith(
            message: safeMessage,
            error: customError,
          ),
        );
      },
    ),
  );

  return dio;
});
