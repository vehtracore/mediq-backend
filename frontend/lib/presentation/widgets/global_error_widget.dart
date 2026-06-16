import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:mediq_app/src/core/utils/ui_error_formatter.dart';

class GlobalErrorWidget extends StatelessWidget {
  final dynamic error;
  final VoidCallback onRetry;

  const GlobalErrorWidget({
    super.key,
    required this.error,
    required this.onRetry,
  });

  static final RegExp _unsafeDetailPattern = RegExp(
    r'<html|traceback|sql|exception:',
    caseSensitive: false,
  );

  String _cleanErrorMessage(dynamic err) {
    if (kDebugMode) {
      return err.toString();
    }

    final message = UIErrorFormatter.getMessage(err).trim();

    if (message.isEmpty ||
        message.length > 150 ||
        _unsafeDetailPattern.hasMatch(message)) {
      return 'An unexpected error occurred. Please try again.';
    }

    return message;
  }

  @override
  Widget build(BuildContext context) {
    final cleanMessage = _cleanErrorMessage(error);

    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24.0),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(
              Icons.wifi_off_rounded,
              size: 64,
              color: Colors.grey,
            ),
            const SizedBox(height: 16),
            Text(
              cleanMessage,
              textAlign: TextAlign.center,
              style: const TextStyle(
                color: Colors.black87,
                fontSize: 16,
              ),
            ),
            const SizedBox(height: 24),
            FilledButton.icon(
              onPressed: onRetry,
              icon: const Icon(Icons.refresh),
              label: const Text('Try Again'),
            ),
          ],
        ),
      ),
    );
  }
}
