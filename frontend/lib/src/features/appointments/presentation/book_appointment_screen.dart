import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';
import 'package:mediq_app/src/features/doctors/data/doctor_model.dart';
import 'package:mediq_app/src/features/appointments/data/appointment_repository.dart';
import 'package:mediq_app/src/features/appointments/data/slot_model.dart';

final slotsProvider = FutureProvider.family.autoDispose<List<DoctorSlot>, int>((
  ref,
  doctorId,
) async {
  final repo = ref.watch(appointmentRepositoryProvider);
  return await repo.getSlots(doctorId);
});

class BookAppointmentScreen extends ConsumerStatefulWidget {
  final Doctor doctor;

  const BookAppointmentScreen({super.key, required this.doctor});

  @override
  ConsumerState<BookAppointmentScreen> createState() =>
      _BookAppointmentScreenState();
}

class _BookAppointmentScreenState extends ConsumerState<BookAppointmentScreen> {
  DateTime? _selectedDate;
  int? _selectedSlotId;
  final TextEditingController _notesController = TextEditingController();
  bool _isBooking = false;

  @override
  void dispose() {
    _notesController.dispose();
    super.dispose();
  }

  bool _isSameDay(DateTime a, DateTime b) {
    return a.year == b.year && a.month == b.month && a.day == b.day;
  }

  Future<void> _handleBooking() async {
    // 1. Validation
    if (_selectedSlotId == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text("Please select a time slot")),
      );
      return;
    }

    // 2. WEB FIX: Unfocus keyboard immediately to prevent "disposed" errors
    FocusScope.of(context).unfocus();

    setState(() => _isBooking = true);

    try {
      // 3. API Call
      final appointment = await ref
          .read(appointmentRepositoryProvider)
          .bookSlot(
            slotId: _selectedSlotId!,
            notes: _notesController.text.trim(),
          );

      // 4. Check mounted before using context
      if (!mounted) return;

      // 5. Explicitly typed map for GoRouter
      final Map<String, dynamic> paymentData = {
        'appointment': appointment,
        'amount': widget.doctor.hourlyRate,
      };

      // 6. WEB FIX: Navigate with a tiny delay to ensure frame rendering is done
      await Future.delayed(const Duration(milliseconds: 50));

      if (mounted) {
        context.push('/payment', extra: paymentData);
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(e.toString()), backgroundColor: Colors.red),
        );
      }
    } finally {
      if (mounted) setState(() => _isBooking = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final slotsAsync = ref.watch(slotsProvider(widget.doctor.id));

    return Scaffold(
      backgroundColor: const Color(0xFFF9FAFB),
      appBar: AppBar(
        title: const Text("Book Appointment"),
        backgroundColor: Colors.white,
        elevation: 0,
        foregroundColor: Colors.black,
      ),
      body: slotsAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (err, stack) => Center(child: Text("Error: $err")),
        data: (allSlots) {
          final availableSlots = allSlots.where((s) => !s.isBooked).toList();

          if (availableSlots.isEmpty) {
            return const Center(child: Text("No available slots found."));
          }

          final availableDates =
              availableSlots
                  .map(
                    (s) => DateTime(
                      s.startTime.year,
                      s.startTime.month,
                      s.startTime.day,
                    ),
                  )
                  .toSet()
                  .toList()
                ..sort();

          DateTime displayDate;
          if (_selectedDate == null ||
              !availableDates.any((d) => _isSameDay(d, _selectedDate!))) {
            displayDate = availableDates.first;
          } else {
            displayDate = _selectedDate!;
          }

          final slotsForDay = availableSlots
              .where((s) => _isSameDay(s.startTime, displayDate))
              .toList();
          slotsForDay.sort((a, b) => a.startTime.compareTo(b.startTime));

          return SingleChildScrollView(
            padding: const EdgeInsets.all(24.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Doctor Info
                Row(
                  children: [
                    CircleAvatar(
                      radius: 30,
                      backgroundImage: NetworkImage(widget.doctor.imageUrl),
                      onBackgroundImageError: (_, __) =>
                          const Icon(Icons.person),
                    ),
                    const SizedBox(width: 16),
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          "Booking with",
                          style: TextStyle(
                            color: Colors.grey[600],
                            fontSize: 14,
                          ),
                        ),
                        Text(
                          widget.doctor.fullName,
                          style: const TextStyle(
                            fontWeight: FontWeight.bold,
                            fontSize: 18,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
                const SizedBox(height: 32),

                // Date Selector
                Text(
                  "Select Date (${availableDates.length} available)",
                  style: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(height: 12),
                SizedBox(
                  height: 80,
                  child: ListView.separated(
                    scrollDirection: Axis.horizontal,
                    itemCount: availableDates.length,
                    separatorBuilder: (_, __) => const SizedBox(width: 12),
                    itemBuilder: (context, index) {
                      final date = availableDates[index];
                      final isSelected = _isSameDay(date, displayDate);

                      return GestureDetector(
                        onTap: () {
                          setState(() {
                            _selectedDate = date;
                            _selectedSlotId = null;
                          });
                        },
                        child: Container(
                          width: 65,
                          decoration: BoxDecoration(
                            color: isSelected
                                ? const Color(0xFF4A90E2)
                                : Colors.white,
                            borderRadius: BorderRadius.circular(12),
                            border: isSelected
                                ? Border.all(color: Colors.transparent)
                                : Border.all(color: Colors.grey.shade300),
                            boxShadow: isSelected
                                ? [
                                    BoxShadow(
                                      color: const Color(
                                        0xFF4A90E2,
                                      ).withOpacity(0.3),
                                      blurRadius: 8,
                                      offset: const Offset(0, 4),
                                    ),
                                  ]
                                : [],
                          ),
                          child: Column(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              Text(
                                DateFormat('E').format(date),
                                style: TextStyle(
                                  color: isSelected
                                      ? Colors.white70
                                      : Colors.grey,
                                  fontSize: 12,
                                ),
                              ),
                              const SizedBox(height: 4),
                              Text(
                                DateFormat('d').format(date),
                                style: TextStyle(
                                  color: isSelected
                                      ? Colors.white
                                      : Colors.black,
                                  fontWeight: FontWeight.bold,
                                  fontSize: 18,
                                ),
                              ),
                            ],
                          ),
                        ),
                      );
                    },
                  ),
                ),

                const SizedBox(height: 32),

                // Slots
                const Text(
                  "Available Time",
                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                ),
                const SizedBox(height: 16),
                Wrap(
                  spacing: 12,
                  runSpacing: 12,
                  children: slotsForDay.map((slot) {
                    final timeStr = DateFormat.jm().format(slot.startTime);
                    final isSelected = _selectedSlotId == slot.id;
                    return ChoiceChip(
                      label: Text(timeStr),
                      selected: isSelected,
                      onSelected: (selected) => setState(
                        () => _selectedSlotId = selected ? slot.id : null,
                      ),
                      selectedColor: const Color(0xFF4A90E2),
                      labelStyle: TextStyle(
                        color: isSelected ? Colors.white : Colors.black,
                        fontWeight: isSelected
                            ? FontWeight.bold
                            : FontWeight.normal,
                      ),
                      backgroundColor: Colors.white,
                      elevation: 1,
                    );
                  }).toList(),
                ),

                const SizedBox(height: 32),
                const Text(
                  "Reason for Visit",
                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _notesController,
                  maxLines: 3,
                  decoration: InputDecoration(
                    hintText: "Briefly describe your symptoms...",
                    filled: true,
                    fillColor: Colors.white,
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(12),
                      borderSide: BorderSide.none,
                    ),
                  ),
                ),

                const SizedBox(height: 40),
                SizedBox(
                  width: double.infinity,
                  height: 50,
                  child: ElevatedButton(
                    onPressed: _isBooking ? null : _handleBooking,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: const Color(0xFF4A90E2),
                      foregroundColor: Colors.white,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12),
                      ),
                    ),
                    child: _isBooking
                        ? const CircularProgressIndicator(color: Colors.white)
                        : const Text(
                            "Proceed to Payment",
                            style: TextStyle(fontSize: 16),
                          ),
                  ),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}
