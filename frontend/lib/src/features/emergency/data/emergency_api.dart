import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/dio_client.dart';
import '../../../core/api/auth_interceptor.dart';

enum NearbySearchStatus { success, empty, unavailable }

class NearbyService {
  final String name;
  final String phoneNumber;
  final String category;

  const NearbyService({
    required this.name,
    required this.phoneNumber,
    required this.category,
  });
}

class NearbySearchResult {
  final NearbySearchStatus status;
  final List<NearbyService> services;

  const NearbySearchResult({required this.status, required this.services});

  const NearbySearchResult.unavailable()
      : status = NearbySearchStatus.unavailable,
        services = const [];
}

/// Emergency network operations built on the app's authenticated Dio client.
class EmergencyApi {
  final Dio _dio;

  EmergencyApi(this._dio);

  Future<NearbySearchResult> searchNearby({
    required double latitude,
    required double longitude,
  }) async {
    try {
      final response = await _dio.get(
        '/api/v1/emergency/local-services',
        queryParameters: {'lat': latitude, 'lon': longitude},
        options: Options(
          sendTimeout: const Duration(seconds: 15),
          receiveTimeout: const Duration(seconds: 15),
        ),
      );

      final data = response.data;
      if (data is! Map) return const NearbySearchResult.unavailable();

      final status = switch (data['status']) {
        'success' => NearbySearchStatus.success,
        'empty' => NearbySearchStatus.empty,
        _ => NearbySearchStatus.unavailable,
      };
      final rawServices = data['services'];
      if (rawServices is! List) {
        return status == NearbySearchStatus.empty
            ? const NearbySearchResult(
                status: NearbySearchStatus.empty,
                services: [],
              )
            : const NearbySearchResult.unavailable();
      }

      final services = rawServices.whereType<Map>().map((item) {
        return NearbyService(
          name: (item['name'] as String? ?? '').trim(),
          phoneNumber: (item['phone_number'] as String? ?? '').trim(),
          category: (item['category'] as String? ?? '').trim(),
        );
      }).where((item) {
        return item.name.isNotEmpty && item.phoneNumber.isNotEmpty;
      }).toList(growable: false);

      if (services.isNotEmpty) {
        return NearbySearchResult(
          status: NearbySearchStatus.success,
          services: services,
        );
      }
      return NearbySearchResult(
        status: status == NearbySearchStatus.unavailable
            ? NearbySearchStatus.unavailable
            : NearbySearchStatus.empty,
        services: const [],
      );
    } on DioException {
      return const NearbySearchResult.unavailable();
    } catch (_) {
      return const NearbySearchResult.unavailable();
    }
  }

  Future<void> requestNextOfKinAlert({
    required double latitude,
    required double longitude,
    required String requestId,
    String? address,
  }) {
    return _dio.post<void>(
      '/api/v1/emergency/trigger',
      data: {
        'latitude': latitude,
        'longitude': longitude,
        'request_id': requestId,
        if (address != null && address.isNotEmpty) 'address': address,
      },
      options: Options(
        sendTimeout: const Duration(seconds: 15),
        receiveTimeout: const Duration(seconds: 15),
        // The backend deduplicates this operation by request_id.
        extra: const {authReplaySafeKey: true},
      ),
    );
  }
}

final emergencyApiProvider = Provider<EmergencyApi>((ref) {
  return EmergencyApi(ref.watch(dioProvider));
});
