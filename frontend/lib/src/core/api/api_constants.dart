import 'package:flutter/foundation.dart';
import 'dart:io';

class ApiConstants {
  // --- 🚀 LIVE PRODUCTION URL ---
  static const String _liveUrl = "https://mediq-backend-m3ik.onrender.com";

  static String get baseUrl {
    if (kReleaseMode) {
      // In Production (APK/Release), ALWAYS use the Live URL
      return _liveUrl;
    }
    
    // In Debug Mode, you can still use the Live URL to test the real server
    // Or uncomment the local logic if you want to go back to offline dev.
    return _liveUrl; 
    
    /* // Localhost Logic (Saved for later if needed)
    if (kIsWeb) {
      return 'http://127.0.0.1:8001';
    } else if (Platform.isAndroid) {
      return 'http://10.0.2.2:8001';
    } else {
      return 'http://127.0.0.1:8001';
    }
    */
  }

  static const String loginEndpoint = '/api/v1/auth/login';
  static const String signupEndpoint = '/api/v1/auth/signup';
}