import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mediq_app/src/features/appointments/data/appointment_model.dart';
import 'package:mediq_app/src/features/auth/data/auth_repository.dart';
import 'package:mediq_app/src/features/profile/presentation/customer_service_sheet.dart';

void main() {
  Future<void> openSheet(
      WidgetTester tester, CustomerServiceSheet sheet) async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: Builder(builder: (context) {
          return TextButton(
            onPressed: () => showModalBottomSheet<dynamic>(
              context: context,
              isScrollControlled: true,
              builder: (_) => sheet,
            ),
            child: const Text('Open service'),
          );
        }),
      ),
    ));
    await tester.tap(find.text('Open service'));
    await tester.pumpAndSettle();
  }

  testWidgets('non-consultation category prefills ordinary support subject',
      (tester) async {
    await openSheet(
      tester,
      CustomerServiceSheet(
        onSendMessage: (
                {required requestId,
                required subject,
                required message}) async =>
            SupportSubmissionResult(requestId: requestId, status: 'sent'),
        loadAppointments: () async => [],
        onSendDispute: ({required appointmentId, required reason}) async {},
      ),
    );
    await tester
        .tap(find.byKey(const Key('service-category-Payment & Subscription')));
    await tester.pumpAndSettle();

    final subject =
        tester.widget<TextField>(find.byKey(const Key('support-subject')));
    expect(subject.controller!.text, 'Payment & Subscription');
  });

  testWidgets('consultation issue uses email and refund uses dispute callback',
      (tester) async {
    final appointment = Appointment(
      id: 14,
      doctorName: 'Dr Ada',
      patientName: 'Patient',
      status: 'completed',
      paymentStatus: 'paid',
      consultationStartedAt: DateTime.now().subtract(const Duration(hours: 1)),
    );
    int? submittedAppointment;
    String? submittedReason;
    final sheet = CustomerServiceSheet(
      onSendMessage: (
              {required requestId, required subject, required message}) async =>
          SupportSubmissionResult(requestId: requestId, status: 'sent'),
      loadAppointments: () async => [appointment],
      onSendDispute: ({required appointmentId, required reason}) async {
        submittedAppointment = appointmentId;
        submittedReason = reason;
      },
    );
    await openSheet(tester, sheet);
    await tester.tap(find.byKey(const Key('service-category-Consultation')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('service-consultation-other')));
    await tester.pumpAndSettle();
    final subject =
        tester.widget<TextField>(find.byKey(const Key('support-subject')));
    expect(subject.controller!.text, 'Other consultation issue');

    await tester.tap(find.byTooltip('Back'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('service-consultation-refund')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('service-appointment-14')));
    await tester.enterText(find.byKey(const Key('service-dispute-reason')),
        'Doctor did not provide the consultation.');
    await tester.tap(find.byKey(const Key('service-dispute-submit')));
    await tester.pumpAndSettle();

    expect(submittedAppointment, 14);
    expect(submittedReason, 'Doctor did not provide the consultation.');
  });
}
