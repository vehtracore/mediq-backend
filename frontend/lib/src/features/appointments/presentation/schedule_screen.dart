import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';
import 'package:mediq_app/src/features/reviews/data/review_repository.dart';
import '../data/appointment_model.dart';
import '../data/appointment_repository.dart';

final myAppointmentsProvider = FutureProvider.autoDispose<List<Appointment>>((
  ref,
) async {
  final repo = ref.watch(appointmentRepositoryProvider);
  return await repo.getMyAppointments();
});

class ScheduleScreen extends ConsumerWidget {
  const ScheduleScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final appointmentsAsync = ref.watch(myAppointmentsProvider);

    return Scaffold(
      backgroundColor: const Color(0xFFF9FAFB),
      appBar: AppBar(
        title: const Text(
          "My Schedule",
          style: TextStyle(color: Colors.black, fontWeight: FontWeight.bold),
        ),
        backgroundColor: Colors.white,
        elevation: 0,
        centerTitle: false,
        automaticallyImplyLeading: false,
      ),
      body: appointmentsAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (err, stack) => Center(child: Text('Error: $err')),
        data: (appointments) {
          if (appointments.isEmpty)
            return const Center(child: Text("No appointments yet"));
          return ListView.separated(
            padding: const EdgeInsets.all(16),
            itemCount: appointments.length,
            separatorBuilder: (_, __) => const SizedBox(height: 16),
            itemBuilder: (context, index) =>
                _AppointmentCard(appointment: appointments[index]),
          );
        },
      ),
    );
  }
}

class _AppointmentCard extends ConsumerWidget {
  final Appointment appointment;
  const _AppointmentCard({required this.appointment});

  void _showRatingSheet(BuildContext context, WidgetRef ref) {
    int selectedRating = 5;
    final commentCtrl = TextEditingController();

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setModalState) => Padding(
          padding: EdgeInsets.only(
            bottom: MediaQuery.of(ctx).viewInsets.bottom,
            left: 24,
            right: 24,
            top: 24,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text(
                "Rate Your Experience",
                style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 16),
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: List.generate(5, (index) {
                  return IconButton(
                    icon: Icon(
                      index < selectedRating ? Icons.star : Icons.star_border,
                      color: Colors.amber,
                      size: 36,
                    ),
                    onPressed: () =>
                        setModalState(() => selectedRating = index + 1),
                  );
                }),
              ),
              const SizedBox(height: 16),
              TextField(
                controller: commentCtrl,
                decoration: const InputDecoration(
                  hintText: "Write a review (optional)",
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 24),
              SizedBox(
                width: double.infinity,
                height: 50,
                child: ElevatedButton(
                  onPressed: () async {
                    Navigator.pop(ctx);
                    try {
                      await ref
                          .read(reviewRepositoryProvider)
                          .submitReview(
                            appointmentId: appointment.id,
                            rating: selectedRating,
                            comment: commentCtrl.text,
                          );
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(
                          content: Text("Review Submitted!"),
                          backgroundColor: Colors.green,
                        ),
                      );

                      // FIX: Refresh the list so the button disappears
                      ref.refresh(myAppointmentsProvider);
                    } catch (e) {
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(
                          content: Text("Failed to submit review"),
                          backgroundColor: Colors.red,
                        ),
                      );
                    }
                  },
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF4A90E2),
                    foregroundColor: Colors.white,
                  ),
                  child: const Text("Submit Review"),
                ),
              ),
              const SizedBox(height: 24),
            ],
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final dayMonth = DateFormat('MMM dd').format(appointment.startTime);
    final time = DateFormat('jm').format(appointment.startTime);
    final isConfirmed = appointment.status == 'confirmed';
    final isCompleted = appointment.status == 'completed';
    final isUnpaid = appointment.paymentStatus == 'unpaid';

    Color statusColor = Colors.orange;
    if (isConfirmed) statusColor = Colors.green;
    if (isCompleted) statusColor = Colors.blue;
    if (appointment.status == 'cancelled') statusColor = Colors.red;

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        boxShadow: [
          BoxShadow(
            color: Colors.grey.withOpacity(0.05),
            blurRadius: 10,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      child: Column(
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 8,
                ),
                decoration: BoxDecoration(
                  color: const Color(0xFF4A90E2).withOpacity(0.1),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Column(
                  children: [
                    Text(
                      dayMonth.split(' ')[1],
                      style: const TextStyle(
                        fontSize: 20,
                        fontWeight: FontWeight.bold,
                        color: Color(0xFF4A90E2),
                      ),
                    ),
                    Text(
                      dayMonth.split(' ')[0],
                      style: const TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.bold,
                        color: Color(0xFF4A90E2),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      time,
                      style: const TextStyle(fontSize: 12, color: Colors.grey),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      appointment.doctorName,
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 8,
                        vertical: 4,
                      ),
                      decoration: BoxDecoration(
                        color: statusColor.withOpacity(0.1),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Text(
                        appointment.status.toUpperCase(),
                        style: TextStyle(
                          color: statusColor,
                          fontSize: 10,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          if (appointment.status != 'cancelled') ...[
            const SizedBox(height: 12),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                if (appointment.status == 'pending' || isConfirmed)
                  TextButton(
                    onPressed: () async {
                      try {
                        await ref
                            .read(appointmentRepositoryProvider)
                            .cancelMyAppointment(appointment.id);
                        ref.refresh(myAppointmentsProvider);
                      } catch (e) {}
                    },
                    child: const Text(
                      "Cancel",
                      style: TextStyle(color: Colors.redAccent),
                    ),
                  ),
                if (isConfirmed) ...[
                  const SizedBox(width: 8),
                  OutlinedButton.icon(
                    onPressed: () => context.push(
                      '/chat',
                      extra: {'title': appointment.doctorName, 'isAi': false},
                    ),
                    icon: const Icon(Icons.chat_bubble_outline, size: 16),
                    label: const Text("Message"),
                  ),
                ],
                if (isUnpaid) ...[
                  const SizedBox(width: 8),
                  ElevatedButton(
                    onPressed: () => context.push(
                      '/payment',
                      extra: {
                        'appointment': appointment,
                        'amount': appointment.amount,
                      },
                    ),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.green,
                      foregroundColor: Colors.white,
                    ),
                    child: const Text("Pay Now"),
                  ),
                ],

                // FIX: Only show if completed AND !hasReview
                if (isCompleted && !appointment.hasReview) ...[
                  const SizedBox(width: 8),
                  ElevatedButton.icon(
                    onPressed: () => _showRatingSheet(context, ref),
                    icon: const Icon(Icons.star, size: 16),
                    label: const Text("Review"),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.amber,
                      foregroundColor: Colors.black,
                    ),
                  ),
                ],
              ],
            ),
          ],
        ],
      ),
    );
  }
}
