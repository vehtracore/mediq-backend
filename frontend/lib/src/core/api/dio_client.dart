import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'api_constants.dart';

final dioProvider = Provider<Dio>((ref) {
  final options = BaseOptions(
    baseUrl: ApiConstants.baseUrl,
    connectTimeout: const Duration(seconds: 30),
    receiveTimeout: const Duration(seconds: 30),
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
      onError: (DioException e, handler) {
        if (kDebugMode) {
          print('❌ [ERR] -> ${e.message}');
          if (e.response != null) {
            print('📜 [RESP BODY] -> ${e.response?.data}');
          }
        }
        return handler.next(e);
      },
    ),
  );

  return dio;
});
