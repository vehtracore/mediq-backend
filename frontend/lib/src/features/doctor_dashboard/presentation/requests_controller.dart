import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/features/appointments/data/appointment_model.dart';
import 'package:mediq_app/src/features/appointments/data/appointment_repository.dart';

// ---------------------------------------------------------------------------
// Tab state — tracks which tab the user is viewing (0 = Requests, 1 = Queue)
// ---------------------------------------------------------------------------
final requestTabProvider = NotifierProvider<RequestTabNotifier, int>(
  RequestTabNotifier.new,
);

class RequestTabNotifier extends Notifier<int> {
  @override
  int build() => 0; // Default to Tab 0 (Direct Requests)

  void setTab(int index) => state = index;
}

// ---------------------------------------------------------------------------
// FIX: Each tab now has its own independent provider so both lists can be
// fetched and cached concurrently. The old design shared one provider for
// both tabs, which meant one tab always saw stale/mismatched data.
// ---------------------------------------------------------------------------

/// Provider for Tab 0: Direct appointment requests directed at this doctor.
final doctorRequestsProvider =
    FutureProvider.autoDispose<List<Appointment>>((ref) async {
  final repo = ref.watch(appointmentRepositoryProvider);

  if (kDebugMode) {
    debugPrint('📋 [requestsProvider] Fetching doctor direct requests...');
  }

  final result = await repo.getDoctorRequests();

  if (kDebugMode) {
    debugPrint(
      '📋 [requestsProvider] Got ${result.length} direct request(s).',
    );
  }

  return result
      .where(
        (a) =>
            a.isVipRequest &&
            a.doctorId != null &&
            a.status == 'pending' &&
            a.paymentStatus == 'unpaid',
      )
      .toList();
});

/// Provider for Tab 1: Unclaimed general-queue GP consultations.
final generalQueueProvider =
    FutureProvider.autoDispose<List<Appointment>>((ref) async {
  final repo = ref.watch(appointmentRepositoryProvider);

  if (kDebugMode) {
    debugPrint('🏥 [queueProvider] Fetching general queue...');
  }

  final result = await repo.getGeneralQueue();

  if (kDebugMode) {
    debugPrint('🏥 [queueProvider] Got ${result.length} queue item(s).');
  }

  return result
      .where(
        (a) =>
            a.isGeneralQueue &&
            a.doctorId == null &&
            a.status == 'pending' &&
            a.paymentStatus == 'paid',
      )
      .toList();
});

// ---------------------------------------------------------------------------
// Mutation controller — wraps accept/decline/claim and invalidates the correct
// provider after each mutation so the list refreshes automatically.
// ---------------------------------------------------------------------------
final requestsControllerProvider =
    AsyncNotifierProvider<RequestsController, void>(RequestsController.new);

class RequestsController extends AsyncNotifier<void> {
  @override
  FutureOr<void> build() {}

  Future<void> accept(int id) async {
    state = const AsyncLoading();
    state = await AsyncValue.guard(() async {
      await ref.read(appointmentRepositoryProvider).acceptAppointment(id);
      ref.invalidate(doctorRequestsProvider);
    });
    if (state.hasError) throw state.error!;
  }

  Future<void> decline(int id) async {
    state = const AsyncLoading();
    state = await AsyncValue.guard(() async {
      await ref.read(appointmentRepositoryProvider).declineAppointment(id);
      ref.invalidate(doctorRequestsProvider);
    });
    if (state.hasError) throw state.error!;
  }

  Future<void> claim(int id) async {
    state = const AsyncLoading();
    state = await AsyncValue.guard(() async {
      await ref.read(appointmentRepositoryProvider).claimAppointment(id);
      ref.invalidate(generalQueueProvider);
    });
    if (state.hasError) throw state.error!;
  }

  Future<void> proposeTime(int id, DateTime time) async {
    state = const AsyncLoading();
    state = await AsyncValue.guard(() async {
      await ref
          .read(appointmentRepositoryProvider)
          .proposeAppointmentTime(id, time);
      ref.invalidate(doctorRequestsProvider);
    });
    if (state.hasError) throw state.error!;
  }
}
