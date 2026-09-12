import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'api_constants.dart';
import '../../features/auth/data/auth_session_coordinator.dart';
import 'auth_interceptor.dart';

final dioProvider = Provider<Dio>((ref) {
  final options = BaseOptions(
    baseUrl: ApiConstants.baseUrl,
    connectTimeout: const Duration(seconds: 90),
    receiveTimeout: const Duration(seconds: 90),
    headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
  );

  final dio = Dio(options);
  dio.interceptors.add(
    AuthenticatedRequestInterceptor(
      dio: dio,
      coordinator: ref.watch(authSessionCoordinatorProvider),
    ),
  );

  return dio;
});
