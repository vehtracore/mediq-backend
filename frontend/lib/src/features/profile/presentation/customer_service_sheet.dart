import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:mediq_app/src/core/utils/ui_error_formatter.dart';
import 'package:mediq_app/src/features/appointments/data/appointment_model.dart';
import 'package:mediq_app/src/features/profile/presentation/support_contact_sheet.dart';

typedef ConsultationDisputeSender = Future<void> Function({
  required int appointmentId,
  required String reason,
});

class CustomerServiceSheet extends StatefulWidget {
  const CustomerServiceSheet({
    super.key,
    required this.onSendMessage,
    required this.loadAppointments,
    required this.onSendDispute,
  });

  final SupportMessageSender onSendMessage;
  final Future<List<Appointment>> Function() loadAppointments;
  final ConsultationDisputeSender onSendDispute;

  @override
  State<CustomerServiceSheet> createState() => _CustomerServiceSheetState();
}

class _CustomerServiceSheetState extends State<CustomerServiceSheet> {
  static const _categories = [
    'Consultation',
    'Payment & Subscription',
    'App / Technical Issue',
    'Account & Access',
    'Other',
  ];

  final _reasonController = TextEditingController();
  String? _category;
  String? _consultationChoice;
  int? _selectedAppointmentId;
  Future<List<Appointment>>? _appointmentsFuture;
  String? _errorText;
  bool _submitting = false;

  void _chooseCategory(String category) {
    setState(() {
      _category = category;
      _consultationChoice = null;
      _errorText = null;
    });
  }

  void _chooseConsultation(String choice) {
    setState(() {
      _consultationChoice = choice;
      _errorText = null;
      if (choice == 'refund') {
        _appointmentsFuture = widget.loadAppointments();
      }
    });
  }

  void _back() {
    setState(() {
      if (_category == 'Consultation' && _consultationChoice != null) {
        _consultationChoice = null;
      } else {
        _category = null;
      }
      _errorText = null;
    });
  }

  Future<void> _submitDispute() async {
    final reason = _reasonController.text.trim();
    if (_selectedAppointmentId == null || reason.isEmpty) {
      setState(() => _errorText =
          'Select a consultation and briefly explain the refund or dispute.');
      return;
    }
    setState(() {
      _submitting = true;
      _errorText = null;
    });
    try {
      await widget.onSendDispute(
        appointmentId: _selectedAppointmentId!,
        reason: reason,
      );
      if (mounted) Navigator.of(context).pop('refund');
    } catch (error) {
      if (mounted) {
        setState(() => _errorText = UIErrorFormatter.getMessage(error));
      }
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  void dispose() {
    _reasonController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (_category != null &&
        (_category != 'Consultation' || _consultationChoice == 'other')) {
      return SupportContactSheet(
        key: ValueKey('customer-service-$_category-$_consultationChoice'),
        initialSubject: _category == 'Consultation'
            ? 'Other consultation issue'
            : _category,
        onSend: widget.onSendMessage,
        onBack: _back,
      );
    }

    return SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(24, 20, 24, 24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              children: [
                if (_category != null)
                  IconButton(
                    tooltip: 'Back',
                    onPressed: _submitting ? null : _back,
                    icon: const Icon(Icons.arrow_back),
                  ),
                Expanded(
                  child: Text(
                    'Customer Service',
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            if (_category == null) ...[
              Text('What do you need help with?',
                  style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 12),
              for (final category in _categories)
                ListTile(
                  key: Key('service-category-$category'),
                  title: Text(category),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => _chooseCategory(category),
                ),
            ] else if (_consultationChoice == null) ...[
              Text('What do you need help with?',
                  style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 12),
              ListTile(
                key: const Key('service-consultation-refund'),
                title: const Text('Refund / dispute consultation'),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => _chooseConsultation('refund'),
              ),
              ListTile(
                key: const Key('service-consultation-other'),
                title: const Text('Other consultation issue'),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => _chooseConsultation('other'),
              ),
            ] else ...[
              Text('Refund / dispute consultation',
                  style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 8),
              const Text(
                'Choose the completed consultation you want reviewed. '
                'Requests are available for 24 hours after the consultation closes.',
              ),
              const SizedBox(height: 16),
              FutureBuilder<List<Appointment>>(
                future: _appointmentsFuture,
                builder: (context, snapshot) {
                  if (snapshot.connectionState != ConnectionState.done) {
                    return const Center(child: CircularProgressIndicator());
                  }
                  if (snapshot.hasError) {
                    return Column(
                      children: [
                        Text(UIErrorFormatter.getMessage(snapshot.error!)),
                        TextButton(
                          onPressed: () => setState(() =>
                              _appointmentsFuture = widget.loadAppointments()),
                          child: const Text('Retry'),
                        ),
                      ],
                    );
                  }
                  final eligible = (snapshot.data ?? [])
                      .where((appointment) => appointment.canPatientReportIssue)
                      .toList();
                  if (eligible.isEmpty) {
                    return const Text(
                      'No consultations are currently eligible for this review.',
                    );
                  }
                  return Column(
                    children: [
                      for (final appointment in eligible)
                        ListTile(
                          key: Key('service-appointment-${appointment.id}'),
                          title: Text(appointment.doctorName),
                          subtitle: Text(appointment.startTime == null
                              ? 'Appointment #${appointment.id}'
                              : '${DateFormat.yMMMd().add_jm().format(appointment.startTime!)} · #${appointment.id}'),
                          selected: _selectedAppointmentId == appointment.id,
                          trailing: Icon(
                            _selectedAppointmentId == appointment.id
                                ? Icons.radio_button_checked
                                : Icons.radio_button_unchecked,
                          ),
                          onTap: _submitting
                              ? null
                              : () => setState(() =>
                                  _selectedAppointmentId = appointment.id),
                        ),
                    ],
                  );
                },
              ),
              const SizedBox(height: 12),
              TextField(
                key: const Key('service-dispute-reason'),
                controller: _reasonController,
                enabled: !_submitting,
                maxLength: 1000,
                maxLines: 4,
                decoration: const InputDecoration(
                  labelText: 'What happened?',
                  border: OutlineInputBorder(),
                ),
              ),
              if (_errorText != null)
                Text(_errorText!,
                    style:
                        TextStyle(color: Theme.of(context).colorScheme.error)),
              const SizedBox(height: 12),
              FilledButton(
                key: const Key('service-dispute-submit'),
                onPressed: _submitting ? null : _submitDispute,
                child:
                    Text(_submitting ? 'Submitting...' : 'Submit for review'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
