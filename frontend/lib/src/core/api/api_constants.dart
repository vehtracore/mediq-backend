import 'dart:io';
import 'package:flutter/foundation.dart'; // For kIsWeb

class ApiConstants {
  // Logic to switch between Emulator localhost (10.0.2.2) and Computer localhost (127.0.0.1)
  static String get baseUrl {
    if (kIsWeb) {
      return 'http://127.0.0.1:8001';
    } else if (Platform.isAndroid) {
      return 'http://10.0.2.2:8001';
    } else {
      return 'http://127.0.0.1:8001';
    }
  }

  // Endpoints
  static const String signupEndpoint = '/api/v1/auth/signup';
}
