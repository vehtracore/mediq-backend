import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mediq_app/src/features/patient_dashboard/presentation/widgets/home_widgets.dart';

void main() {
  testWidgets('Emergency tile creates one activation ID in the route',
      (tester) async {
    final router = GoRouter(
      initialLocation: '/',
      routes: [
        GoRoute(
          path: '/',
          builder: (_, __) => const Scaffold(body: QuickActionGrid()),
        ),
        GoRoute(
          path: '/emergency',
          builder: (_, state) => Scaffold(
            body: Text(state.uri.queryParameters['activationId'] ?? 'missing'),
          ),
        ),
      ],
    );

    await tester.pumpWidget(
      ProviderScope(child: MaterialApp.router(routerConfig: router)),
    );
    await tester.tap(find.text('Emergency'));
    await tester.pumpAndSettle();

    final activationText = tester.widget<Text>(find.byType(Text)).data!;
    expect(
      activationText,
      matches(
        RegExp(
          r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
        ),
      ),
    );
  });
}
