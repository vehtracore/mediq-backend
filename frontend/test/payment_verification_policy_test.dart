import 'package:flutter_test/flutter_test.dart';
import 'package:mediq_app/src/features/payments/domain/payment_verification_policy.dart';

void main() {
  test('automatic verification is bounded and stays below 5 per minute', () {
    expect(PaymentVerificationPolicy.automaticDelays, hasLength(3));
    expect(PaymentVerificationPolicy.automaticDelay(3), isNull);

    final starts = <Duration>[];
    var elapsed = Duration.zero;
    for (final delay in PaymentVerificationPolicy.automaticDelays) {
      elapsed += delay;
      starts.add(elapsed);
    }

    for (final windowStart in [Duration.zero, ...starts]) {
      final inWindow = starts.where((start) {
        return start >= windowStart &&
            start < windowStart + const Duration(minutes: 1);
      });
      expect(inWindow.length, lessThan(5));
    }
  });

  test('reopening checkout cannot reset the automatic verification budget', () {
    final budget = PaymentVerificationBudget();

    for (var i = 0; i < 3; i++) {
      expect(budget.nextAutomaticDelay, isNotNull);
      budget.recordAutomaticAttempt();
    }

    expect(budget.completedAutomaticAttempts, 3);
    expect(budget.nextAutomaticDelay, isNull);
    expect(budget.nextAutomaticDelay, isNull);
  });

  test('minimum interval bounds resume and manual verification requests', () {
    final now = DateTime.utc(2026, 9, 15, 12);
    final delay = PaymentVerificationPolicy.effectiveDelay(
      requestedDelay: Duration.zero,
      now: now,
      lastRequestAt: now.subtract(const Duration(seconds: 3)),
    );

    expect(delay, const Duration(seconds: 9));

    final possibleStarts = <Duration>[];
    var elapsed = Duration.zero;
    while (elapsed < const Duration(minutes: 1)) {
      possibleStarts.add(elapsed);
      elapsed += PaymentVerificationPolicy.minimumRequestInterval;
    }
    expect(possibleStarts, hasLength(5));
  });

  test('provider Retry-After takes precedence over automatic cadence', () {
    final now = DateTime.utc(2026, 9, 15, 12);
    final delay = PaymentVerificationPolicy.effectiveDelay(
      requestedDelay: const Duration(seconds: 15),
      now: now,
      notBefore: now.add(const Duration(seconds: 75)),
    );

    expect(delay, const Duration(seconds: 75));
  });
}
