import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:mediq_app/src/features/appointments/data/appointment_model.dart';
import 'package:mediq_app/src/features/doctor_dashboard/presentation/requests_controller.dart';

class DoctorRequestsScreen extends ConsumerWidget {
  const DoctorRequestsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final requestsAsync = ref.watch(requestsControllerProvider);
    final currentTab = ref.watch(requestTabProvider);

    return Column(
      children: [
        // --- Tabs ---
        Padding(
          padding: const EdgeInsets.all(16.0),
          child: SegmentedButton<int>(
            segments: const [
              ButtonSegment(
                value: 0,
                label: Text("My Requests"),
                icon: Icon(Icons.person),
              ),
              ButtonSegment(
                value: 1,
                label: Text("General Queue"),
                icon: Icon(Icons.groups),
              ),
            ],
            selected: {currentTab},
            onSelectionChanged: (Set<int> newSelection) {
              // UPDATED: Using the new method
              ref.read(requestTabProvider.notifier).setTab(newSelection.first);
            },
            style: ButtonStyle(
              backgroundColor: MaterialStateProperty.resolveWith<Color>((
                Set<MaterialState> states,
              ) {
                if (states.contains(MaterialState.selected)) {
                  return const Color(0xFF4A90E2);
                }
                return Colors.white;
              }),
              foregroundColor: MaterialStateProperty.resolveWith<Color>((
                Set<MaterialState> states,
              ) {
                if (states.contains(MaterialState.selected)) {
                  return Colors.white;
                }
                return Colors.black;
              }),
            ),
          ),
        ),

        // --- List ---
        Expanded(
          child: requestsAsync.when(
            loading: () => const Center(child: CircularProgressIndicator()),
            error: (err, stack) => Center(child: Text("Error: $err")),
            data: (appointments) {
              if (appointments.isEmpty) {
                return Center(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(Icons.inbox, size: 64, color: Colors.grey[300]),
                      const SizedBox(height: 16),
                      Text(
                        "No pending items",
                        style: TextStyle(color: Colors.grey[600]),
                      ),
                    ],
                  ),
                );
              }

              return ListView.separated(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                itemCount: appointments.length,
                separatorBuilder: (_, __) => const SizedBox(height: 16),
                itemBuilder: (context, index) {
                  return _RequestCard(
                    appointment: appointments[index],
                    isGeneral: currentTab == 1,
                  );
                },
              );
            },
          ),
        ),
      ],
    );
  }
}

class _RequestCard extends ConsumerWidget {
  final Appointment appointment;
  final bool isGeneral;

  const _RequestCard({required this.appointment, required this.isGeneral});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final controller = ref.read(requestsControllerProvider.notifier);
    final dateStr = DateFormat('MMM dd, yyyy').format(appointment.startTime);
    final timeStr = DateFormat('jm').format(appointment.startTime);

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        boxShadow: [
          BoxShadow(
            color: Colors.grey.withOpacity(0.08),
            blurRadius: 10,
            offset: const Offset(0, 4),
          ),
        ],
        border: isGeneral
            ? Border.all(color: Colors.orange.withOpacity(0.3))
            : null,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              CircleAvatar(
                backgroundColor: isGeneral
                    ? Colors.orange.withOpacity(0.1)
                    : const Color(0xFF4A90E2).withOpacity(0.1),
                child: Icon(
                  isGeneral ? Icons.flash_on : Icons.person,
                  color: isGeneral ? Colors.orange : const Color(0xFF4A90E2),
                ),
              ),
              const SizedBox(width: 12),
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    isGeneral ? "General Queue Request" : "Direct Request",
                    style: const TextStyle(
                      fontWeight: FontWeight.bold,
                      fontSize: 16,
                    ),
                  ),
                  Text(
                    "Requested: $timeStr",
                    style: TextStyle(color: Colors.grey[600], fontSize: 13),
                  ),
                ],
              ),
            ],
          ),
          const SizedBox(height: 12),
          Text(
            appointment.notes ?? "No notes",
            style: TextStyle(
              color: Colors.grey[800],
              fontStyle: FontStyle.italic,
            ),
          ),
          const SizedBox(height: 16),

          if (isGeneral)
            SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: () => controller.claim(appointment.id),
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.orange,
                  foregroundColor: Colors.white,
                ),
                child: const Text("Claim Patient"),
              ),
            )
          else
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: () => controller.decline(appointment.id),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: Colors.red,
                    ),
                    child: const Text("Decline"),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: ElevatedButton(
                    onPressed: () => controller.accept(appointment.id),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.green,
                      foregroundColor: Colors.white,
                    ),
                    child: const Text("Accept"),
                  ),
                ),
              ],
            ),
        ],
      ),
    );
  }
}
