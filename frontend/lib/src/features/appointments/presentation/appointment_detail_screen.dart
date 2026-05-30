import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/features/appointments/data/appointment_model.dart';
import 'package:mediq_app/src/features/appointments/data/appointment_repository.dart';
import 'package:intl/intl.dart';

// Use a family provider to fetch the specific appointment by ID
final appointmentDetailProvider = FutureProvider.family.autoDispose<Appointment, int>((ref, id) async {
  final repo = ref.watch(appointmentRepositoryProvider);
  // As a fallback, since getAppointmentById might not exist yet on the backend,
  // we try to fetch all appointments and find the one with this ID.
  // Ideally, you would add `getAppointmentById` to your repository.
  final allAppointments = await repo.getMyAppointments();
  return allAppointments.firstWhere((a) => a.id == id, orElse: () => throw Exception('Appointment not found'));
});

class AppointmentDetailScreen extends ConsumerWidget {
  final int appointmentId;

  const AppointmentDetailScreen({super.key, required this.appointmentId});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Watch the specific appointment data
    final asyncAppointment = ref.watch(appointmentDetailProvider(appointmentId));
    final theme = Theme.of(context);

    return Scaffold(
      backgroundColor: theme.scaffoldBackgroundColor,
      appBar: AppBar(
        title: const Text("Appointment Details"),
      ),
      body: asyncAppointment.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (err, stack) => Center(child: Text("Error loading details: $err")),
        data: (appointment) {
          final dateStr = appointment.startTime != null 
              ? DateFormat('MMM dd, yyyy').format(appointment.startTime!) 
              : 'Pending Date';
          final timeStr = appointment.startTime != null 
              ? DateFormat('jm').format(appointment.startTime!) 
              : 'Pending Time';

          return SingleChildScrollView(
            padding: const EdgeInsets.all(24.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text("Patient: ${appointment.patientName}", style: theme.textTheme.titleLarge),
                const SizedBox(height: 16),
                Text("Date: $dateStr • $timeStr"),
                const SizedBox(height: 16),
                Text("Status: ${appointment.status.toUpperCase()}"),
                const SizedBox(height: 16),
                if (appointment.notes != null && appointment.notes!.isNotEmpty)
                  Text("Notes: ${appointment.notes}"),
              ],
            ),
          );
        },
      ),
    );
  }
}
