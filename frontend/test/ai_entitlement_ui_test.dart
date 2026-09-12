import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mediq_app/src/features/chat/presentation/ai_chat_screen.dart';
import 'package:mediq_app/src/features/vault/data/vault_record.dart';
import 'package:mediq_app/src/features/vault/presentation/vault_screen.dart';

Widget _host(Widget child) => MaterialApp(home: Scaffold(body: child));

VaultRecord _summaryRecord() => VaultRecord(
      id: 'summary-id',
      type: 'ai_summary',
      date: DateTime.utc(2026, 9, 5),
      topicOrReason: 'AI Symptom Analysis',
      details: 'Previously saved summary',
    );

VaultRecord _consultationRecord() => VaultRecord(
      id: 'consultation-id',
      type: 'consultation',
      date: DateTime.utc(2026, 9, 5),
      topicOrReason: 'Follow-up consultation',
      details: 'Clinical notes',
    );

void main() {
  testWidgets('Free exit is ephemeral and exposes no functional save action',
      (tester) async {
    var saveCalls = 0;
    var exitCalls = 0;
    await tester.pumpWidget(
      _host(
        AiChatExitDialog(
          canSave: false,
          onCancel: () {},
          onExit: () => exitCalls += 1,
          onSave: () async => saveCalls += 1,
        ),
      ),
    );

    expect(find.text('Exit & Save'), findsNothing);
    expect(find.text('Exit'), findsOneWidget);
    await tester.tap(find.text('Exit'));
    expect(exitCalls, 1);
    expect(saveCalls, 0);
  });

  testWidgets('Paid exit retains Exit & Save', (tester) async {
    var saveCalls = 0;
    await tester.pumpWidget(
      _host(
        AiChatExitDialog(
          canSave: true,
          onCancel: () {},
          onExit: () {},
          onSave: () async => saveCalls += 1,
        ),
      ),
    );

    expect(find.text('Exit & Save'), findsOneWidget);
    await tester.tap(find.text('Exit & Save'));
    await tester.pump();
    expect(saveCalls, 1);
  });

  testWidgets(
      'Free AI summary remains visible with export/delete and locked continuation',
      (tester) async {
    var continueCalls = 0;
    await tester.pumpWidget(
      _host(
        AISummaryCard(
          record: _summaryRecord(),
          canContinue: false,
          onExportPdf: () {},
          onDelete: () {},
          onContinue: () => continueCalls += 1,
        ),
      ),
    );

    expect(find.text('AI Symptom Analysis'), findsOneWidget);
    await tester.tap(find.byIcon(Icons.more_vert_rounded));
    await tester.pumpAndSettle();

    expect(find.text('Continue with AI'), findsOneWidget);
    expect(find.text('Export PDF'), findsOneWidget);
    expect(find.text('Delete'), findsOneWidget);
    final locked = tester.widget<PopupMenuItem<String>>(
      find.widgetWithText(PopupMenuItem<String>, 'Continue with AI'),
    );
    expect(locked.enabled, isFalse);
    expect(continueCalls, 0);
  });

  testWidgets('Paid AI summary exposes functional continuation',
      (tester) async {
    var continueCalls = 0;
    await tester.pumpWidget(
      _host(
        AISummaryCard(
          record: _summaryRecord(),
          canContinue: true,
          onExportPdf: () {},
          onDelete: () {},
          onContinue: () => continueCalls += 1,
        ),
      ),
    );

    await tester.tap(find.byIcon(Icons.more_vert_rounded));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Continue with AI'));
    await tester.pumpAndSettle();

    expect(continueCalls, 1);
  });

  testWidgets('AI entitlement does not alter other Vault record actions',
      (tester) async {
    var exportCalls = 0;
    await tester.pumpWidget(
      _host(
        ConsultationCard(
          record: _consultationRecord(),
          onExportPdf: () => exportCalls += 1,
        ),
      ),
    );

    expect(find.text('Follow-up consultation'), findsOneWidget);
    await tester.tap(find.byIcon(Icons.more_vert_rounded));
    await tester.pumpAndSettle();

    expect(find.text('Continue with AI'), findsNothing);
    expect(find.text('Export PDF'), findsOneWidget);
    await tester.tap(find.text('Export PDF'));
    await tester.pumpAndSettle();
    expect(exportCalls, 1);
  });
}
