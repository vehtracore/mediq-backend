import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mediq_app/src/features/auth/data/auth_state_provider.dart';
import 'package:mediq_app/src/features/vault/data/vault_record.dart';
import 'package:mediq_app/src/features/vault/data/vault_repository.dart';

class _FakeVaultRepository extends VaultRepository {
  _FakeVaultRepository(this.records) : super(Dio());

  final List<VaultRecord> records;
  int calls = 0;

  @override
  Future<List<VaultRecord>> getVaultHistory() async {
    calls += 1;
    return records;
  }
}

class _SequencedVaultRepository extends VaultRepository {
  _SequencedVaultRepository(this.results) : super(Dio());

  final List<List<VaultRecord>> results;
  int calls = 0;

  @override
  Future<List<VaultRecord>> getVaultHistory() async {
    final result = results[calls];
    calls += 1;
    return result;
  }
}

VaultRecord _recordFor(String account) => VaultRecord(
      id: account,
      type: 'ai_summary',
      date: DateTime.utc(2026),
      topicOrReason: '$account summary',
    );

void main() {
  test('cached Account A key cannot load while Account B is authenticated',
      () async {
    final repository = _FakeVaultRepository([_recordFor('B')]);
    final container = ProviderContainer(overrides: [
      authUserIdProvider.overrideWith((ref) => 'B'),
      vaultRepositoryProvider.overrideWithValue(repository),
    ]);
    addTearDown(container.dispose);

    expect(await container.read(vaultHistoryProvider('A').future), isEmpty);
    expect(repository.calls, 0);
    expect(
      (await container.read(vaultHistoryProvider('B').future)).single.id,
      'B',
    );
  });

  test('signed-out identity cannot display an earlier Vault cache key',
      () async {
    final repository = _FakeVaultRepository([_recordFor('A')]);
    final container = ProviderContainer(overrides: [
      authUserIdProvider.overrideWith((ref) => null),
      vaultRepositoryProvider.overrideWithValue(repository),
    ]);
    addTearDown(container.dispose);

    expect(await container.read(vaultHistoryProvider('A').future), isEmpty);
    expect(repository.calls, 0);
  });

  test('A to signed-out to B transition never reuses Account A records',
      () async {
    final identity = StateProvider<String?>((ref) => 'A');
    final repository = _SequencedVaultRepository([
      [_recordFor('A')],
      [_recordFor('B')],
    ]);
    final container = ProviderContainer(overrides: [
      authUserIdProvider.overrideWith((ref) => ref.watch(identity)),
      vaultRepositoryProvider.overrideWithValue(repository),
    ]);
    addTearDown(container.dispose);

    expect(
      (await container.read(vaultHistoryProvider('A').future)).single.id,
      'A',
    );

    container.read(identity.notifier).state = null;
    expect(await container.read(vaultHistoryProvider('A').future), isEmpty);

    container.read(identity.notifier).state = 'B';
    expect(
      (await container.read(vaultHistoryProvider('B').future)).single.id,
      'B',
    );
    expect(repository.calls, 2);
  });
}
