import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import '../../doctors/data/doctor_repository.dart';
import '../../auth/data/auth_repository.dart';
import '../../appointments/data/appointment_repository.dart';
import '../../../shared/presentation/widgets/skeleton_loader.dart';
import '../../../../presentation/widgets/global_error_widget.dart';

// Provider to get current doctor ID
final myDoctorProfileProvider = FutureProvider.autoDispose((ref) async {
  return await ref.watch(authRepositoryProvider).getMyDoctorProfile();
});

// Provider for the doctor's own upcoming (unbooked) slots.
// Invalidated after every create or delete so the list stays in sync.
final myDoctorSlotsProvider =
    FutureProvider.autoDispose<List<dynamic>>((ref) async {
  final doctor = await ref.watch(myDoctorProfileProvider.future);
  // Re-use the existing GET endpoint — only returns unbooked slots.
  final repo = ref.watch(appointmentRepositoryProvider);
  return await repo.getSlots(doctor.id);
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
  int? _creatingHour;
  int? _deletingSlotId;

  bool get _isCreating => _creatingHour != null;

  bool _isSelectedDate(DateTime value) {
    return value.year == _selectedDate.year &&
        value.month == _selectedDate.month &&
        value.day == _selectedDate.day;
  }

  Set<int> _existingSlotHoursForSelectedDate(List<dynamic> slots) {
    return slots
        .where((slot) => _isSelectedDate(slot.startTime as DateTime))
        .map<int>((slot) => (slot.startTime as DateTime).hour)
        .toSet();
  }

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
    setState(() => _creatingHour = hour);
    try {
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

      // Refresh slot list immediately after creation
      ref.invalidate(myDoctorSlotsProvider);

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
      if (mounted) setState(() => _creatingHour = null);
    }
  }

  Future<void> _deleteSlot(BuildContext context, int slotId, String label) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Delete Slot?'),
        content: Text('Remove the $label slot from your availability?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Keep'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: TextButton.styleFrom(foregroundColor: Colors.red),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() => _deletingSlotId = slotId);
    try {
      await ref.read(doctorRepositoryProvider).deleteSlot(slotId);
      ref.invalidate(myDoctorSlotsProvider);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Slot removed.'),
            backgroundColor: Colors.green,
            duration: Duration(seconds: 1),
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Error: $e'),
            backgroundColor: Colors.red,
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _deletingSlotId = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    final doctorAsync = ref.watch(myDoctorProfileProvider);
    final theme = Theme.of(context);

    return Scaffold(
      backgroundColor: theme.scaffoldBackgroundColor,
      appBar: AppBar(
        title: Text("Manage Availability", style: theme.textTheme.titleLarge),
        backgroundColor: theme.appBarTheme.backgroundColor,
        elevation: 0,
      ),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(myDoctorProfileProvider),
        child: doctorAsync.when(
          loading: () => ListView.builder(
            physics: const AlwaysScrollableScrollPhysics(),
            itemCount: 5,
            padding: const EdgeInsets.all(16),
            itemBuilder: (context, index) => Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: SkeletonLoader(child: Container(height: 60, width: double.infinity, decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(12)))),
            ),
          ),
          error: (e, _) => ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            children: [
              SizedBox(
                height: MediaQuery.of(context).size.height * 0.7,
                child: GlobalErrorWidget(
                  error: e,
                  onRetry: () => ref.invalidate(myDoctorProfileProvider),
                ),
              ),
            ],
          ),
          data: (doctor) {
            final slotsAsync = ref.watch(myDoctorSlotsProvider);
            final existingSlotHours = slotsAsync.maybeWhen(
              data: _existingSlotHoursForSelectedDate,
              orElse: () => <int>{},
            );
            final addableHours = _standardHours
                .where((hour) => !existingSlotHours.contains(hour))
                .toList();
            final canAddSlots = slotsAsync.hasValue;

            return SingleChildScrollView(
              physics: const AlwaysScrollableScrollPhysics(),
              child: Padding(
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
                          border: Border.all(
                            color: theme.brightness == Brightness.dark
                                ? Colors.grey.shade800
                                : Colors.grey.shade300,
                          ),
                          borderRadius: BorderRadius.circular(12),
                          color: theme.cardColor,
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
                                    color: Colors.grey[500],
                                  ),
                                ),
                                const SizedBox(height: 4),
                                Text(
                                  DateFormat(
                                    'EEEE, MMM d, yyyy',
                                  ).format(_selectedDate),
                                  style: theme.textTheme.bodyMedium?.copyWith(
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
                      children: addableHours.isEmpty
                          ? [
                              Text(
                                'All standard times are already added for this date.',
                                style: TextStyle(
                                  color: Colors.grey[500],
                                  fontSize: 13,
                                ),
                              ),
                            ]
                          : addableHours.map((hour) {
                              final timeLabel = DateFormat(
                                'h:mm a',
                              ).format(DateTime(2023, 1, 1, hour));
                              final isCreatingThisHour =
                                  _creatingHour == hour;

                              return ActionChip(
                                label: Text(
                                  isCreatingThisHour
                                      ? 'Adding...'
                                      : timeLabel,
                                  style: theme.textTheme.bodyMedium,
                                ),
                                backgroundColor: theme.cardColor,
                                surfaceTintColor: Colors.transparent,
                                elevation: 1,
                                onPressed: _isCreating || !canAddSlots
                                    ? null
                                    : () => _addSlot(hour, doctor.id),
                                avatar: isCreatingThisHour
                                    ? const SizedBox(
                                        width: 16,
                                        height: 16,
                                        child: CircularProgressIndicator(
                                          strokeWidth: 2,
                                        ),
                                      )
                                    : const Icon(
                                        Icons.add,
                                        size: 16,
                                        color: Color(0xFF4A90E2),
                                      ),
                              );
                            }).toList(),
                    ),
    
                    const SizedBox(height: 40),

                    // --- Upcoming Slots List (with delete) ---
                    const Text(
                      'Your Upcoming Slots:',
                      style: TextStyle(fontWeight: FontWeight.bold),
                    ),
                    const SizedBox(height: 8),
                    slotsAsync.when(
                      loading: () => const Padding(
                        padding: EdgeInsets.symmetric(vertical: 8),
                        child: LinearProgressIndicator(),
                      ),
                      error: (e, _) => Text(
                        'Could not load slots: $e',
                        style: const TextStyle(
                            color: Colors.red, fontSize: 12),
                      ),
                      data: (slots) {
                        if (slots.isEmpty) {
                          return Padding(
                            padding:
                                const EdgeInsets.symmetric(vertical: 12),
                            child: Text(
                              'No upcoming slots. Add some above.',
                              style: TextStyle(
                                  color: Colors.grey[500], fontSize: 13),
                            ),
                          );
                        }
                        return Column(
                          children: slots.map((slot) {
                            final label = DateFormat('EEE, MMM d • h:mm a')
                                .format(slot.startTime);
                            return Container(
                              margin: const EdgeInsets.only(bottom: 8),
                              padding: const EdgeInsets.symmetric(
                                  horizontal: 16, vertical: 10),
                              decoration: BoxDecoration(
                                color: theme.cardColor,
                                borderRadius: BorderRadius.circular(12),
                                border: Border.all(
                                    color: theme.brightness == Brightness.dark
                                        ? Colors.grey.shade800
                                        : Colors.grey.shade200),
                              ),
                              child: Row(
                                children: [
                                  const Icon(Icons.schedule,
                                      size: 16, color: Color(0xFF4A90E2)),
                                  const SizedBox(width: 10),
                                  Expanded(
                                    child: Text(label,
                                        style: theme.textTheme.bodyMedium
                                            ?.copyWith(
                                                fontWeight: FontWeight.w500)),
                                  ),
                                  // Only allow deletion of unbooked slots
                                  // (the endpoint returns only unbooked ones,
                                  // but we guard explicitly for clarity).
                                  if (!slot.isBooked)
                                    IconButton(
                                      icon: _deletingSlotId == slot.id
                                          ? const SizedBox(
                                              width: 20,
                                              height: 20,
                                              child: CircularProgressIndicator(
                                                strokeWidth: 2,
                                                color: Colors.red,
                                              ),
                                            )
                                          : const Icon(
                                              Icons.delete_outline,
                                              color: Colors.red,
                                              size: 20,
                                            ),
                                      tooltip: 'Delete slot',
                                      onPressed: _deletingSlotId != null
                                          ? null
                                          : () => _deleteSlot(
                                              context,
                                              slot.id,
                                              label,
                                            ),
                                    ),
                                ],
                              ),
                            );
                          }).toList(),
                        );
                      },
                    ),

                    const SizedBox(height: 24),

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
              ),
            );
          },
        ),
      ),
    );
  }
}
