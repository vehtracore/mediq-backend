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

        // --- 401 UNAUTHORIZED CHECK: Silent Refresh ---
        if (e.response?.statusCode == 401) {
          if (kDebugMode) print('🔄 [AUTH] -> 401 Detected. Attempting token refresh...');
          
          try {
            // Read refresh token
            final refreshToken = await storage.read(key: 'refresh_token', aOptions: getAndroidOptions());
            
            if (refreshToken == null || refreshToken.isEmpty) {
              if (kDebugMode) print('⚠️ [AUTH] -> No refresh token found. Logging out.');
              await storage.delete(key: 'auth_token', aOptions: getAndroidOptions());
              await storage.delete(key: 'refresh_token', aOptions: getAndroidOptions());
              
              final context = rootNavigatorKey.currentContext;
              if (context != null && context.mounted) {
                GoRouter.of(context).go('/auth');
              }
              return handler.next(e);
            }
            
            // Make dedicated request to refresh
            final tokenDio = Dio(BaseOptions(baseUrl: ApiConstants.baseUrl));
            final refreshResponse = await tokenDio.post(
              '/api/v1/auth/refresh',
              data: {'refresh_token': refreshToken},
            );
            
            if (refreshResponse.statusCode == 200) {
              final newAccessToken = refreshResponse.data['access_token'];
              final newRefreshToken = refreshResponse.data['refresh_token'];
              
              // Securely save new tokens
              await storage.write(key: 'auth_token', value: newAccessToken, aOptions: getAndroidOptions());
              await storage.write(key: 'refresh_token', value: newRefreshToken, aOptions: getAndroidOptions());
              
              if (kDebugMode) print('✅ [AUTH] -> Token refreshed successfully!');
              
              // Update request header with new token
              e.requestOptions.headers['Authorization'] = 'Bearer $newAccessToken';
              
              // Retry the original request
              final retryResponse = await dio.fetch(e.requestOptions);
              return handler.resolve(retryResponse);
            }
          } catch (refreshErr) {
            if (kDebugMode) print('❌ [AUTH] -> Refresh failed: $refreshErr. Logging out.');
            await storage.delete(key: 'auth_token', aOptions: getAndroidOptions());
            await storage.delete(key: 'refresh_token', aOptions: getAndroidOptions());
            
            final context = rootNavigatorKey.currentContext;
            if (context != null && context.mounted) {
               GoRouter.of(context).go('/auth');
            }
            return handler.next(e);
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
