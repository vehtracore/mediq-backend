import 'package:flutter/foundation.dart';

class ApiConstants {
  // --- 🚀 LIVE PRODUCTION URL ---
  static const String _liveUrl = "https://api.mdqplus.com";

  static String get baseUrl {
    if (kReleaseMode) {
      return _liveUrl;
    }

    // In Debug Mode, still use the Live URL to test the real server.
    // To switch to local dev, use kIsWeb from foundation.dart (NOT dart:io Platform).
    return _liveUrl;

    /* // Localhost Logic (Web-safe version)
    // import 'package:flutter/foundation.dart' provides kIsWeb
    // For Android emulator detection without dart:io, use a const flag or env var.
    if (kIsWeb) {
      return 'http://127.0.0.1:8001';
    } else {
      return 'http://10.0.2.2:8001'; // Android emulator
    }
    */
  }

  static const String loginEndpoint = '/api/v1/auth/login';
  static const String signupEndpoint = '/api/v1/auth/signup';
}
