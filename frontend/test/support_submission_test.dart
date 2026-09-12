import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mediq_app/src/core/api/app_exception.dart';
import 'package:mediq_app/src/features/auth/data/auth_repository.dart';
import 'package:mediq_app/src/features/profile/presentation/support_contact_sheet.dart';

Dio _respondingDio(Object data, {int statusCode = 200}) {
  final dio = Dio();
  dio.interceptors.add(
    InterceptorsWrapper(
      onRequest: (options, handler) {
        final response = Response<dynamic>(
          requestOptions: options,
          statusCode: statusCode,
          data: data,
        );
        if (statusCode >= 400) {
          handler.reject(
            DioException.badResponse(
              statusCode: statusCode,
              requestOptions: options,
              response: response,
            ),
          );
        } else {
          handler.resolve(response);
        }
      },
    ),
  );
  return dio;
}

void main() {
  const requestId = '11111111-1111-4111-8111-111111111111';

  test('repository accepts only matching provider-accepted sent response',
      () async {
    final repository = AuthRepository(
      _respondingDio({
        'request_id': requestId,
        'status': 'sent',
      }),
    );

    final result = await repository.sendSupportMessage(
      requestId: requestId,
      subject: 'Help',
      message: 'Please assist',
    );

    expect(result.requestId, requestId);
    expect(result.isSent, isTrue);
  });

  test('repository rejects persisted-only and failed HTTP responses', () async {
    final persistedOnly = AuthRepository(
      _respondingDio({
        'request_id': requestId,
        'status': 'received',
      }),
    );
    final unavailable = AuthRepository(
      _respondingDio(
        {'detail': 'Temporarily unavailable'},
        statusCode: 503,
      ),
    );

    for (final repository in [persistedOnly, unavailable]) {
      await expectLater(
        repository.sendSupportMessage(
          requestId: requestId,
          subject: 'Help',
          message: 'Please assist',
        ),
        throwsA(isA<AppException>()),
      );
    }
  });

  testWidgets('failure keeps draft and unchanged retry keeps request ID',
      (tester) async {
    final requestIds = <String>[];
    var calls = 0;

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SupportContactSheet(
            createRequestId: () => requestId,
            onSend: ({
              required requestId,
              required subject,
              required message,
            }) async {
              requestIds.add(requestId);
              calls += 1;
              if (calls == 1) throw StateError('provider unavailable');
              return SupportSubmissionResult(
                requestId: requestId,
                status: 'failed',
              );
            },
          ),
        ),
      ),
    );

    await tester.enterText(find.byKey(const Key('support-subject')), 'Billing');
    await tester.enterText(
      find.byKey(const Key('support-message')),
      'Please help with my account',
    );
    await tester.tap(find.byKey(const Key('support-submit')));
    await tester.pumpAndSettle();

    expect(find.text('Billing'), findsOneWidget);
    expect(find.text('Please help with my account'), findsOneWidget);
    expect(find.byKey(const Key('support-error')), findsOneWidget);
    expect(find.text('Retry'), findsOneWidget);

    await tester.tap(find.byKey(const Key('support-submit')));
    await tester.pumpAndSettle();

    expect(requestIds, [requestId, requestId]);
    expect(find.text('Billing'), findsOneWidget);
    expect(find.byType(SupportContactSheet), findsOneWidget);
  });

  testWidgets('sheet closes only after a matching sent result', (tester) async {
    final requestIds = <String>[];

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => ElevatedButton(
              onPressed: () => showModalBottomSheet<bool>(
                context: context,
                builder: (_) => SupportContactSheet(
                  createRequestId: () => requestId,
                  onSend: ({
                    required requestId,
                    required subject,
                    required message,
                  }) async {
                    requestIds.add(requestId);
                    return SupportSubmissionResult(
                      requestId: requestId,
                      status: 'sent',
                    );
                  },
                ),
              ),
              child: const Text('Open support'),
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.text('Open support'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('support-subject')), 'Account');
    await tester.enterText(
      find.byKey(const Key('support-message')),
      'Please assist',
    );
    await tester.tap(find.byKey(const Key('support-submit')));
    await tester.pumpAndSettle();

    expect(requestIds, [requestId]);
    expect(find.byType(SupportContactSheet), findsNothing);
    expect(find.text('Open support'), findsOneWidget);
  });

  testWidgets('editing a failed draft starts a new submission ID',
      (tester) async {
    final generated = <String>[
      '11111111-1111-4111-8111-111111111111',
      '22222222-2222-4222-8222-222222222222',
    ];
    final seen = <String>[];

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SupportContactSheet(
            createRequestId: () => generated.removeAt(0),
            onSend: ({
              required requestId,
              required subject,
              required message,
            }) async {
              seen.add(requestId);
              throw StateError('provider unavailable');
            },
          ),
        ),
      ),
    );

    await tester.enterText(find.byKey(const Key('support-subject')), 'First');
    await tester.enterText(find.byKey(const Key('support-message')), 'Message');
    await tester.tap(find.byKey(const Key('support-submit')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('support-subject')), 'Changed');
    await tester.tap(find.byKey(const Key('support-submit')));
    await tester.pumpAndSettle();

    expect(generated, isEmpty);
    expect(seen, const [
      '11111111-1111-4111-8111-111111111111',
      '22222222-2222-4222-8222-222222222222',
    ]);
  });
}
