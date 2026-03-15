import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:go_router/go_router.dart';
import 'api_constants.dart';
import '../router/app_router.dart';

final dioProvider = Provider<Dio>((ref) {
  final options = BaseOptions(
    baseUrl: ApiConstants.baseUrl,
    connectTimeout: const Duration(seconds: 90),
    receiveTimeout: const Duration(seconds: 90),
    headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
  );

  final dio = Dio(options);

  // --- FIX: USE CONSISTENT OPTIONS ---
  const storage = FlutterSecureStorage();

  // Define the EXACT same options as used in storage_service.dart to ensure we read the same file
  AndroidOptions getAndroidOptions() => const AndroidOptions(
        encryptedSharedPreferences: true,
      );

  dio.interceptors.add(
    InterceptorsWrapper(
      onRequest: (options, handler) async {
        try {
          // 1. Read using the secure options
          // Tries 'auth_token' first (standard for this app)
          String? token = await storage.read(
              key: 'auth_token', aOptions: getAndroidOptions());

          // Fallback: Check 'token' just in case of legacy saving
          if (token == null) {
            token =
                await storage.read(key: 'token', aOptions: getAndroidOptions());
          }

          // 2. Attach Token
          if (token != null && token.isNotEmpty) {
            options.headers['Authorization'] = 'Bearer $token';
          } else {
            if (kDebugMode)
              print('⚠️ [AUTH] -> No token found in secure storage.');
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

        // --- SUSPENSION CHECK: 403 with "Account suspended" ---
        if (e.response?.statusCode == 403) {
          final data = e.response?.data;
          final detail = data is Map ? data['detail'] : data?.toString();

          if (detail != null &&
              detail.toString().contains('Account suspended')) {
            if (kDebugMode) {
              print('🚫 [AUTH] -> Account suspended. Logging out...');
            }

            // 1. Clear token
            await storage.delete(
                key: 'auth_token', aOptions: getAndroidOptions());

            // 2. Show dialog & navigate to login
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
                        GoRouter.of(context).go('/auth');
                      },
                      child: const Text('Understood'),
                    ),
                  ],
                ),
              );
            }
          }
        }

        return handler.next(e);
      },
    ),
  );

  return dio;
});
