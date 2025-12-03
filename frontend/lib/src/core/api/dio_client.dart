import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/core/storage/storage_service.dart'; // Absolute import
import 'api_constants.dart';

final dioProvider = Provider<Dio>((ref) {
  final storage = ref.watch(storageServiceProvider);

  final options = BaseOptions(
    baseUrl: ApiConstants.baseUrl,
    connectTimeout: const Duration(seconds: 30),
    receiveTimeout: const Duration(seconds: 30),
    headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
  );

  final dio = Dio(options);

  dio.interceptors.add(
    InterceptorsWrapper(
      onRequest: (options, handler) async {
        // 1. Get Token from Storage
        final token = await storage.getToken();

        // 2. If token exists, add to headers
        if (token != null && token.isNotEmpty) {
          options.headers['Authorization'] = 'Bearer $token';
        }

        // Debug logging
        if (kDebugMode) {
          print('🌐 [REQ] -> ${options.method} ${options.path}');
          // Don't print full token for security, just confirmation
          if (token != null) print('🔑 [AUTH] -> Bearer attached');
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
          // --- ADD THIS SECTION ---
          if (e.response != null) {
            print('📜 [RESP BODY] -> ${e.response?.data}');
          }
          // ------------------------
        }
        return handler.next(e);
      },
    ),
  );

  return dio;
});
