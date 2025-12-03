import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import '../../doctors/data/doctor_repository.dart';
import '../../auth/data/auth_repository.dart';

// Provider to get current doctor ID
final myDoctorProfileProvider = FutureProvider.autoDispose((ref) async {
  return await ref.watch(authRepositoryProvider).getMyDoctorProfile();
});

class DoctorAvailabilityScreen extends ConsumerStatefulWidget {
  const DoctorAvailabilityScreen({super.key});

  @override
  ConsumerState<DoctorAvailabilityScreen> createState() =>
      _DoctorAvailabilityScreenState();
}

class _DoctorAvailabilityScreenState
    extends ConsumerState<DoctorAvailabilityScreen> {
  // Default to tomorrow
  DateTime _selectedDate = DateTime.now().add(const Duration(days: 1));
  final List<int> _standardHours = [9, 10, 11, 12, 13, 14, 15, 16, 17];
  bool _isCreating = false;

  Future<void> _selectDate(BuildContext context) async {
    final DateTime? picked = await showDatePicker(
      context: context,
      initialDate: _selectedDate,
      firstDate: DateTime.now(),
      // CONSTRAINT: Restrict to next 30 days
      lastDate: DateTime.now().add(const Duration(days: 30)),
      builder: (context, child) {
        return Theme(
          data: Theme.of(context).copyWith(
            colorScheme: const ColorScheme.light(primary: Color(0xFF4A90E2)),
          ),
          child: child!,
        );
      },
    );
    if (picked != null && picked != _selectedDate) {
      setState(() {
        _selectedDate = picked;
      });
    }
  }

  Future<void> _addSlot(int hour, int doctorId) async {
    setState(() => _isCreating = true);
    try {
      // Create DateTime for the slot
      final slotTime = DateTime(
        _selectedDate.year,
        _selectedDate.month,
        _selectedDate.day,
        hour,
        0,
      );

      await ref
          .read(doctorRepositoryProvider)
          .createSlot(doctorId: doctorId, startTime: slotTime);

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              "Slot added for ${DateFormat('h:mm a').format(slotTime)}",
            ),
            backgroundColor: Colors.green,
            duration: const Duration(seconds: 1),
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text("Failed: $e"), backgroundColor: Colors.red),
        );
      }
    } finally {
      if (mounted) setState(() => _isCreating = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final doctorAsync = ref.watch(myDoctorProfileProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text("Manage Availability"),
        backgroundColor: Colors.white,
        foregroundColor: Colors.black,
        elevation: 0,
      ),
      body: doctorAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text("Error loading profile: $e")),
        data: (doctor) {
          return Padding(
            padding: const EdgeInsets.all(16.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // --- Date Picker ---
                InkWell(
                  onTap: () => _selectDate(context),
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 16,
                      vertical: 12,
                    ),
                    decoration: BoxDecoration(
                      border: Border.all(color: Colors.grey.shade300),
                      borderRadius: BorderRadius.circular(12),
                      color: Colors.white,
                    ),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              "Selected Date",
                              style: TextStyle(
                                fontSize: 12,
                                color: Colors.grey[600],
                              ),
                            ),
                            const SizedBox(height: 4),
                            Text(
                              DateFormat(
                                'EEEE, MMM d, yyyy',
                              ).format(_selectedDate),
                              style: const TextStyle(
                                fontSize: 16,
                                fontWeight: FontWeight.bold,
                              ),
                            ),
                          ],
                        ),
                        const Icon(
                          Icons.calendar_today,
                          color: Color(0xFF4A90E2),
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 24),

                // --- Slots Grid ---
                const Text(
                  "Tap to add a slot:",
                  style: TextStyle(fontWeight: FontWeight.bold),
                ),
                const SizedBox(height: 12),

                Wrap(
                  spacing: 12,
                  runSpacing: 12,
                  children: _standardHours.map((hour) {
                    final timeLabel = DateFormat(
                      'h:mm a',
                    ).format(DateTime(2023, 1, 1, hour));

                    return ActionChip(
                      label: Text(timeLabel),
                      backgroundColor: Colors.white,
                      surfaceTintColor: Colors.white,
                      elevation: 1,
                      onPressed: _isCreating
                          ? null
                          : () => _addSlot(hour, doctor.id),
                      avatar: const Icon(
                        Icons.add,
                        size: 16,
                        color: Color(0xFF4A90E2),
                      ),
                    );
                  }).toList(),
                ),

                const SizedBox(height: 40),

                // --- Explanation ---
                Container(
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: Colors.blue.withOpacity(0.05),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: const Row(
                    children: [
                      Icon(Icons.info_outline, color: Color(0xFF4A90E2)),
                      SizedBox(width: 12),
                      Expanded(
                        child: Text(
                          "Slots added here will immediately appear in search results for patients to book.",
                          style: TextStyle(fontSize: 12, color: Colors.grey),
                        ),
                      ),
                    ],
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
