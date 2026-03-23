import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

class GlobalErrorWidget extends StatelessWidget {
  final FlutterErrorDetails details;

  const GlobalErrorWidget({super.key, required this.details});

  @override
  Widget build(BuildContext context) {
    // If the error happens during the build phase of a widget deep in the tree,
    // we still want to show a clean UI. We wrap it in a Material to ensure
    // text styles and spacing work correctly even outside a Scaffold context.
    return Material(
      color: Colors.white,
      child: Center(
        child: Padding(
          padding: const EdgeInsets.all(24.0),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(
                Icons.error_outline,
                color: Colors.red,
                size: 64,
              ),
              const SizedBox(height: 16),
              const Text(
                "Oops, something went wrong displaying this page.",
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.bold,
                  color: Colors.black87,
                ),
              ),
              const SizedBox(height: 16),
              ElevatedButton.icon(
                onPressed: () {
                  // Attempt to pop the current route if possible
                  if (Navigator.canPop(context)) {
                    Navigator.pop(context);
                  } else {
                    // Fallback: If we can't pop, just rebuild or let the user navigate via other means
                    // (In a real app, this might trigger a deep link back home router context)
                    debugPrint('Cannot pop from ErrorWidget.');
                  }
                },
                icon: const Icon(Icons.arrow_back),
                label: const Text("Go Back"),
              ),
              if (kDebugMode) ...[
                const SizedBox(height: 32),
                const Divider(),
                const SizedBox(height: 16),
                const Text(
                  "Debug Details:",
                  style: TextStyle(fontWeight: FontWeight.bold, color: Colors.red),
                ),
                const SizedBox(height: 8),
                Text(
                  details.exceptionAsString(),
                  textAlign: TextAlign.center,
                  style: const TextStyle(fontSize: 12, color: Colors.black54),
                ),
              ]
            ],
          ),
        ),
      ),
    );
  }
}
