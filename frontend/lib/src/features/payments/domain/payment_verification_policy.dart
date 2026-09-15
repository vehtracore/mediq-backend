class PaymentVerificationPolicy {
  PaymentVerificationPolicy._();

  static const minimumRequestInterval = Duration(seconds: 12);
  static const automaticDelays = <Duration>[
    Duration(seconds: 15),
    Duration(seconds: 30),
    Duration(seconds: 60),
  ];
  static const defaultRetryAfter = Duration(seconds: 60);

  static Duration? automaticDelay(int completedAttempts) {
    if (completedAttempts < 0 || completedAttempts >= automaticDelays.length) {
      return null;
    }
    return automaticDelays[completedAttempts];
  }

  static Duration effectiveDelay({
    required Duration requestedDelay,
    required DateTime now,
    DateTime? lastRequestAt,
    DateTime? notBefore,
  }) {
    var allowedAt = now.add(requestedDelay);
    if (lastRequestAt != null) {
      final intervalAllowedAt = lastRequestAt.add(minimumRequestInterval);
      if (intervalAllowedAt.isAfter(allowedAt)) allowedAt = intervalAllowedAt;
    }
    if (notBefore != null && notBefore.isAfter(allowedAt)) {
      allowedAt = notBefore;
    }
    final delay = allowedAt.difference(now);
    return delay.isNegative ? Duration.zero : delay;
  }
}

class PaymentVerificationBudget {
  int _completedAutomaticAttempts = 0;

  int get completedAutomaticAttempts => _completedAutomaticAttempts;

  Duration? get nextAutomaticDelay => PaymentVerificationPolicy.automaticDelay(
        _completedAutomaticAttempts,
      );

  void recordAutomaticAttempt() {
    if (nextAutomaticDelay != null) _completedAutomaticAttempts += 1;
  }
}
