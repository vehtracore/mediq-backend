import 'dart:async';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/features/appointments/data/appointment_model.dart';
import 'package:mediq_app/src/features/appointments/data/appointment_repository.dart';

// --- NEW: Tab State Management (Notifier instead of StateProvider) ---
final requestTabProvider = NotifierProvider<RequestTabNotifier, int>(
  RequestTabNotifier.new,
);

class RequestTabNotifier extends Notifier<int> {
  @override
  int build() {
    return 0; // Default to Tab 0 (Direct Requests)
  }

  void setTab(int index) {
    state = index;
  }
}

// --- Requests Controller ---
final requestsControllerProvider =
    AsyncNotifierProvider<RequestsController, List<Appointment>>(
      RequestsController.new,
    );

class RequestsController extends AsyncNotifier<List<Appointment>> {
  @override
  FutureOr<List<Appointment>> build() async {
    // Watch tab to auto-refresh when switching
    final tab = ref.watch(requestTabProvider);
    return _fetchData(tab);
  }

  Future<List<Appointment>> _fetchData(int tabIndex) async {
    final repo = ref.watch(appointmentRepositoryProvider);
    // 0 = Direct Requests, 1 = General Queue
    if (tabIndex == 0) {
      return await repo.getDoctorRequests();
    } else {
      return await repo.getGeneralQueue();
    }
  }

  Future<void> accept(int id) async {
    final repo = ref.read(appointmentRepositoryProvider);
    state = const AsyncLoading();
    state = await AsyncValue.guard(() async {
      await repo.acceptAppointment(id);
      return _fetchData(ref.read(requestTabProvider));
    });
  }

  Future<void> decline(int id) async {
    final repo = ref.read(appointmentRepositoryProvider);
    state = const AsyncLoading();
    state = await AsyncValue.guard(() async {
      await repo.declineAppointment(id);
      return _fetchData(ref.read(requestTabProvider));
    });
  }

  Future<void> claim(int id) async {
    final repo = ref.read(appointmentRepositoryProvider);
    state = const AsyncLoading();
    state = await AsyncValue.guard(() async {
      await repo.claimAppointment(id);
      return _fetchData(ref.read(requestTabProvider));
    });
  }
}
