import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'package:mediq_app/src/core/api/app_exception.dart';
import 'package:mediq_app/src/core/utils/ui_error_formatter.dart';

import 'vault_record.dart';

// ---------------------------------------------------------------------------
// Repository provider
// ---------------------------------------------------------------------------

final vaultRepositoryProvider = Provider<VaultRepository>((ref) {
  return VaultRepository(ref.watch(dioProvider));
});

// ---------------------------------------------------------------------------
// FutureProvider — consumed by the UI
// ---------------------------------------------------------------------------

/// Fetches the patient's full Health Vault history from the backend.
/// Returns a list of [VaultRecord] sorted newest-first (server-side).
final vaultHistoryProvider = FutureProvider<List<VaultRecord>>((ref) async {
  return ref.watch(vaultRepositoryProvider).getVaultHistory();
});

// ---------------------------------------------------------------------------
// Repository
// ---------------------------------------------------------------------------

class VaultRepository {
  final Dio _dio;

  VaultRepository(this._dio);

  Future<List<VaultRecord>> getVaultHistory() async {
    const ep = 'GET /api/v1/vault/history';
    if (kDebugMode) debugPrint('📋 [Vault] → $ep');

    try {
      final response = await _dio.get('/api/v1/vault/history');

      if (kDebugMode) {
        debugPrint('📬 [Vault] ← ${response.statusCode} '
            'count=${(response.data as List).length}');
      }

      final List<dynamic> raw = response.data as List<dynamic>;
      return raw
          .map((json) => VaultRecord.fromJson(json as Map<String, dynamic>))
          .toList();
    } catch (e) {
      throw AppException(
        UIErrorFormatter.getMessage(e),
        originalException: e,
      );
    }
  }
}
