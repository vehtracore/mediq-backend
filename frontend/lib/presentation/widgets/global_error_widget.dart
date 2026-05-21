import 'package:flutter/material.dart';

class GlobalErrorWidget extends StatelessWidget {
  final dynamic error;
  final VoidCallback onRetry;

  const GlobalErrorWidget({
    super.key,
    required this.error,
    required this.onRetry,
  });

  String _cleanErrorMessage(dynamic err) {
    String message = err.toString();

    if (message.startsWith('Exception: ')) {
      message = message.substring('Exception: '.length);
    }

    if (message.contains('DioException')) {
      final exp = RegExp(r'\[.+\]\s*(.+)');
      final match = exp.firstMatch(message);
      if (match != null && match.group(1) != null) {
        message = match.group(1)!.trim();
      } else {
        message = 'A network connection error occurred.';
      }
    }

    if (message.contains('Exception:')) {
      message = message.replaceAll('Exception:', '').trim();
    }

    if (message.isEmpty || message.length > 150) {
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
