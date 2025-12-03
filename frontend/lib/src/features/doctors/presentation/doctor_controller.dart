import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../data/doctor_model.dart';
import '../data/doctor_repository.dart';

// AutoDispose ensures we re-fetch data if the user leaves and comes back later
final doctorListProvider = FutureProvider.autoDispose<List<Doctor>>((
  ref,
) async {
  final repository = ref.watch(doctorRepositoryProvider);
  return await repository.getDoctors();
});
