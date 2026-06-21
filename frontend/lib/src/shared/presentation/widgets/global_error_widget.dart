import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

class GlobalErrorWidget extends StatefulWidget {
  final FlutterErrorDetails details;
  final VoidCallback? onRetry;

  const GlobalErrorWidget({super.key, required this.details, this.onRetry});

  @override
  State<GlobalErrorWidget> createState() => _GlobalErrorWidgetState();
}

class _GlobalErrorWidgetState extends State<GlobalErrorWidget> {
  bool _showDebugDetails = false;

  @override
  Widget build(BuildContext context) {
    const friendlyMessage =
        'Something went wrong displaying this page.\nPlease go back and try again.';

    // Only ever expose debug details in debug mode — and only when user expands
    final debugDetails = kDebugMode
        ? [
            widget.details.exceptionAsString(),
            widget.details.stack?.toString() ?? 'No stack trace available.',
          ].join('\n\n')
        : null;

    return Material(
      color: Colors.white,
      child: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24.0),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(
                  Icons.error_outline_rounded,
                  color: Color(0xFFE57373),
                  size: 64,
                ),
                const SizedBox(height: 16),
                const Text(
                  'Oops! Something went wrong.',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.bold,
                    color: Colors.black87,
                  ),
                ),
                const SizedBox(height: 8),
                const Text(
                  friendlyMessage,
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    fontSize: 14,
                    color: Colors.black54,
                    height: 1.5,
                  ),
                ),
                const SizedBox(height: 24),
                ElevatedButton.icon(
                  onPressed: () {
                    if (Navigator.canPop(context)) {
                      Navigator.pop(context);
                    }
                  },
                  icon: const Icon(Icons.arrow_back),
                  label: const Text('Go Back'),
                ),
                if (widget.onRetry != null) ...[
                  const SizedBox(height: 12),
                  ElevatedButton.icon(
                    onPressed: widget.onRetry,
                    icon: const Icon(Icons.refresh),
                    label: const Text('Try Again'),
                  ),
                ],
                // ── Debug toggle — never visible in production ─────────────
                if (debugDetails != null) ...[
                  const SizedBox(height: 24),
                  TextButton.icon(
                    onPressed: () => setState(
                        () => _showDebugDetails = !_showDebugDetails),
                    icon: Icon(_showDebugDetails
                        ? Icons.expand_less
                        : Icons.expand_more),
                    label: Text(_showDebugDetails
                        ? 'Hide debug info'
                        : 'Show debug info'),
                    style: TextButton.styleFrom(
                      foregroundColor: Colors.red.shade300,
                    ),
                  ),
                  if (_showDebugDetails) ...[
                    const Divider(),
                    const SizedBox(height: 8),
                    ConstrainedBox(
                      constraints: const BoxConstraints(maxHeight: 240),
                      child: SingleChildScrollView(
                        child: Text(
                          debugDetails,
                          textAlign: TextAlign.left,
                          style: const TextStyle(
                              fontSize: 11, color: Colors.black54),
                        ),
                      ),
                    ),
                  ],
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}
