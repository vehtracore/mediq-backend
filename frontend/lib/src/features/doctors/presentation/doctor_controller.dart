import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../data/doctor_model.dart';
import '../data/doctor_repository.dart';

/// Purpose: Drives the Doctor Search and Booking screens by providing a full, 
/// updated list of verified medical professionals available on the platform.
///
/// Data Source: Communicates with `doctorRepositoryProvider` (`getDoctors()` API endpoint).
///
/// Invalidation Strategy: Should be explicitly invalidated via `ref.invalidate(doctorListProvider)` 
/// on pull-to-refresh on the search screen, or retry taps in GlobalErrorWidget.
/// AutoDispose ensures we re-fetch data if the user leaves and comes back later.
///
/// Error & Loading Annotations: Exceptions thrown by the API (like `DioException`) are caught by Riverpod 
/// and translated into clean localized strings by the `GlobalErrorWidget` wrapped around this provider's `error` state.
// AutoDispose ensures we re-fetch data if the user leaves and comes back later
final doctorListProvider = FutureProvider.autoDispose<List<Doctor>>((
  ref,
) async {
  final repository = ref.watch(doctorRepositoryProvider);
  return await repository.getDoctors();
});
