import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:mediq_app/src/features/appointments/data/appointment_model.dart';
import 'package:mediq_app/src/features/doctor_dashboard/presentation/requests_controller.dart';
import 'package:mediq_app/src/shared/presentation/widgets/skeleton_loader.dart';
import 'package:mediq_app/src/shared/presentation/widgets/error_state_widget.dart';
import 'package:mediq_app/src/core/api/app_exception.dart';
import 'package:dio/dio.dart';

class DoctorRequestsScreen extends ConsumerStatefulWidget {
  const DoctorRequestsScreen({super.key});

  @override
  ConsumerState<DoctorRequestsScreen> createState() =>
      _DoctorRequestsScreenState();
}

class _DoctorRequestsScreenState extends ConsumerState<DoctorRequestsScreen>
    with SingleTickerProviderStateMixin {
  late TabController _tabController;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 2, vsync: this);
    _tabController.addListener(() {
      if (!_tabController.indexIsChanging) {
        ref.read(requestTabProvider.notifier).setTab(_tabController.index);
      }
    });
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    // Keep TabController in sync if state is changed externally
    final currentTab = ref.watch(requestTabProvider);
    if (_tabController.index != currentTab) {
      _tabController.animateTo(currentTab);
    }

    // ── FIX: Each tab watches its OWN independent provider ──────────────────
    // Previously both tabs consumed the same requestsControllerProvider, which
    // meant whichever tab wasn't "active" always showed a skeleton because the
    // cached data was for the other tab. Now each tab fetches independently and
    // both results are cached concurrently by Riverpod.
    final requestsAsync = ref.watch(doctorRequestsProvider);
    final queueAsync = ref.watch(generalQueueProvider);

    return Column(
      children: [
        // --- Tab Bar ---
        TabBar(
          controller: _tabController,
          labelColor: theme.colorScheme.primary,
          unselectedLabelColor: theme.colorScheme.onSurfaceVariant,
          indicatorColor: theme.colorScheme.primary,
          tabs: const [
            Tab(text: 'My Requests'),
            Tab(text: 'General Queue'),
          ],
        ),

        // --- Tab Content ---
        Expanded(
          child: TabBarView(
            controller: _tabController,
            children: [
              // Tab 0 — Direct requests assigned to this doctor
              _buildList(
                context: context,
                asyncValue: requestsAsync,
                isGeneral: false,
                onRefresh: () => ref.invalidate(doctorRequestsProvider),
              ),
              // Tab 1 — Unassigned GP queue items
              _buildList(
                context: context,
                asyncValue: queueAsync,
                isGeneral: true,
                onRefresh: () => ref.invalidate(generalQueueProvider),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildList({
    required BuildContext context,
    required AsyncValue<List<Appointment>> asyncValue,
    required bool isGeneral,
    required VoidCallback onRefresh,
  }) {
    final theme = Theme.of(context);

    return RefreshIndicator(
      onRefresh: () async {
        onRefresh();
        await Future.delayed(const Duration(milliseconds: 500));
      },
      child: asyncValue.when(
        loading: () => ListView.builder(
          padding: const EdgeInsets.only(top: 16, left: 16, right: 16),
          itemCount: 5,
          itemBuilder: (_, __) => const RequestCardSkeleton(),
        ),
        error: (err, stack) {
          String errorMessage = err.toString();
          if (err is DioException && err.error is AppException) {
            errorMessage = (err.error as AppException).message;
          }
          return ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            children: [
              SizedBox(
                height: 400,
                child: ErrorStateWidget(
                  message: errorMessage,
                  onRetry: onRefresh,
                ),
              ),
            ],
          );
        },
        data: (appointments) {
          if (appointments.isEmpty) {
            return ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              children: [
                SizedBox(
                  height: 300,
                  child: Center(
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(Icons.inbox, size: 64, color: theme.disabledColor),
                        const SizedBox(height: 16),
                        Text(
                          isGeneral
                              ? 'No patients in the queue'
                              : 'No pending requests',
                          style: theme.textTheme.bodyMedium,
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            );
          }

          return ListView.separated(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.all(16),
            itemCount: appointments.length,
            separatorBuilder: (_, __) => const SizedBox(height: 16),
            itemBuilder: (context, index) {
              return _RequestCard(
                appointment: appointments[index],
                isGeneral: isGeneral,
              );
            },
          );
        },
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Request Card
// ---------------------------------------------------------------------------
class _RequestCard extends ConsumerStatefulWidget {
  final Appointment appointment;
  final bool isGeneral;

  const _RequestCard({required this.appointment, required this.isGeneral});

  @override
  ConsumerState<_RequestCard> createState() => _RequestCardState();
}

class _RequestCardState extends ConsumerState<_RequestCard> {
  String? _loadingAction;

  Future<void> _runAction(
    String action,
    Future<void> Function() task,
  ) async {
    if (_loadingAction != null) return;

    setState(() => _loadingAction = action);
    try {
      await task();
    } finally {
      if (mounted) setState(() => _loadingAction = null);
    }
  }

  Future<void> _confirmDecline(int appointmentId) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogCtx) => AlertDialog(
        title: const Text('Decline Request'),
        content: const Text('Are you sure you want to decline this request?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogCtx).pop(false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.of(dialogCtx).pop(true),
            style: TextButton.styleFrom(foregroundColor: Colors.red),
            child: const Text('Decline'),
          ),
        ],
      ),
    );

    if (confirmed != true || !mounted) return;

    await _runAction(
      'decline',
      () => ref.read(requestsControllerProvider.notifier).decline(appointmentId),
    );
  }

  Widget _buttonSpinner({Color color = Colors.white}) {
    return SizedBox(
      width: 18,
      height: 18,
      child: CircularProgressIndicator(
        strokeWidth: 2,
        color: color,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final controller = ref.read(requestsControllerProvider.notifier);
    final appointment = widget.appointment;
    final isGeneral = widget.isGeneral;
    final isBusy = _loadingAction != null;
    final timeStr = appointment.startTime != null ? DateFormat('jm').format(appointment.startTime!) : 'Pending';
    final theme = Theme.of(context);

    // In doctor-side views the backend encodes the *patient* name in the
    // `doctor_name` field (the field is repurposed for display). The new
    // `patient_name` field is now the authoritative source; fall back to
    // `doctor_name` for backwards compatibility with any cached responses.
    final patientDisplayName =
        appointment.patientName.isNotEmpty && appointment.patientName != 'Patient'
            ? appointment.patientName
            : appointment.doctorName;

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: theme.cardTheme.color,
        borderRadius: BorderRadius.circular(16),
        boxShadow: theme.brightness == Brightness.dark
            ? []
            : [
                BoxShadow(
                  color: Colors.grey.withValues(alpha: 0.08),
                  blurRadius: 10,
                  offset: const Offset(0, 4),
                )
              ],
        border: isGeneral
            ? Border.all(color: Colors.orange.withValues(alpha: 0.3))
            : null,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // ── Header Row ──────────────────────────────────────────────────
          Row(
            children: [
              CircleAvatar(
                backgroundColor: isGeneral
                    ? Colors.orange.withValues(alpha: 0.1)
                    : const Color(0xFF4A90E2).withValues(alpha: 0.1),
                child: Icon(
                  isGeneral ? Icons.flash_on : Icons.person,
                  color: isGeneral ? Colors.orange : const Color(0xFF4A90E2),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      patientDisplayName,
                      style: theme.textTheme.titleMedium
                          ?.copyWith(fontWeight: FontWeight.bold),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                    Text(
                      isGeneral ? 'GP Queue · $timeStr' : 'Direct VIP Request',
                      style: theme.textTheme.bodySmall,
                    ),
                  ],
                ),
              ),
              // Payment badge
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: appointment.paymentStatus == 'paid'
                      ? Colors.green.withValues(alpha: 0.1)
                      : Colors.amber.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  appointment.paymentStatus.toUpperCase(),
                  style: TextStyle(
                    fontSize: 10,
                    fontWeight: FontWeight.bold,
                    color: appointment.paymentStatus == 'paid'
                        ? Colors.green
                        : Colors.orange,
                  ),
                ),
              ),
            ],
          ),

          // ── Notes ────────────────────────────────────────────────────────
          if (appointment.notes != null && appointment.notes!.isNotEmpty) ...[
            const SizedBox(height: 12),
            Text(
              appointment.notes!,
              style: theme.textTheme.bodyMedium
                  ?.copyWith(fontStyle: FontStyle.italic),
            ),
          ],

          const SizedBox(height: 16),

          // ── Actions ──────────────────────────────────────────────────────
          if (isGeneral)
            SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: isBusy
                    ? null
                    : () => _runAction(
                          'claim',
                          () => controller.claim(appointment.id),
                        ),
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.orange,
                  foregroundColor: Colors.white,
                ),
                child: _loadingAction == 'claim'
                    ? _buttonSpinner()
                    : const Text('Claim Patient'),
              ),
            )
          else
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: isBusy
                        ? null
                        : () => _confirmDecline(appointment.id),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: Colors.red,
                    ),
                    child: _loadingAction == 'decline'
                        ? _buttonSpinner(color: Colors.red)
                        : const Text('Decline'),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: ElevatedButton(
                    onPressed: isBusy
                        ? null
                        : () async {
                      final selectedDate = await showDatePicker(
                        context: context,
                        initialDate: DateTime.now(),
                        firstDate: DateTime.now(),
                        lastDate: DateTime.now().add(const Duration(days: 30)),
                      );
                      if (selectedDate != null && context.mounted) {
                        final selectedTime = await showTimePicker(
                          context: context,
                          initialTime: TimeOfDay.now(),
                        );
                        if (selectedTime != null) {
                          final dt = DateTime(
                            selectedDate.year,
                            selectedDate.month,
                            selectedDate.day,
                            selectedTime.hour,
                            selectedTime.minute,
                          );
                          await _runAction(
                            'accept',
                            () => controller.proposeTime(appointment.id, dt),
                          );
                        }
                      }
                    },
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.green,
                      foregroundColor: Colors.white,
                    ),
                    child: _loadingAction == 'accept'
                        ? _buttonSpinner()
                        : const Text('Accept (Propose Time)'),
                  ),
                ),
              ],
            ),
        ],
      ),
    );
  }
}
