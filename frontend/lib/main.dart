import 'dart:ui';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'src/core/router/app_router.dart';
import 'src/core/theme/app_theme.dart';
import 'src/features/auth/presentation/user_controller.dart';
import 'src/features/auth/data/user_model.dart';
import 'src/shared/presentation/widgets/global_error_widget.dart';

import 'package:firebase_core/firebase_core.dart';
import 'package:mediq_app/src/core/services/notification_service.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
// import 'package:web/web.dart' as web; // For cleaning URL (Optional)

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  
  // --- 🔥 Firebase Initialization ---
  try {
    await Firebase.initializeApp();
    // In a real app with Riverpod, we would read the provider via a container or let the first screen handle it.
    // However, the prompt asks to init in main or auth controller. 
    // We will initialize NotificationService here for foreground listeners:
    await NotificationService().init();
  } catch (e) {
    debugPrint("Firebase init failed: $e");
  }

  // --- 🔴 Error Boundaries ---
  // 1. Catch synchronous UI rendering errors (Grey Screen of Death)
  ErrorWidget.builder = (FlutterErrorDetails details) {
    // Only return the custom widget in release mode or if we want it in debug too.
    // We already handle kDebugMode inside GlobalErrorWidget to show the stack trace.
    return GlobalErrorWidget(details: details);
  };

  // 2. Catch asynchronous Dart exceptions
  PlatformDispatcher.instance.onError = (error, stack) {
    if (kDebugMode) {
      debugPrint('🚨 [PlatformDispatcher] Asynchronous Error Caught: $error');
      debugPrint('🚨 StackTrace: $stack');
    }
    // TODO: Send to Crashlytics or Sentry here in production
    return true; // Return true to prevent the app from crashing entirely
  };
  // ---------------------------

  // --- 🔴 Google Auth: Capture Token from URL (Web) ---
  final uri = Uri.base; // Get current URL
  
  // 1. Try standard query params (e.g. ?token=...)
  String? token = uri.queryParameters['token'];
  
  // 2. Try Fragment (Hash) params (Common in Flutter Web e.g. /#/auth_callback?token=...)
  if (token == null && uri.fragment.isNotEmpty) {
     try {
       // We construct a dummy URL with the fragment as the path/query to parse it easily
       // Example fragment: "/auth_callback?token=abc"
       final fragmentUri = Uri.parse("http://dummy${uri.fragment}");
       token = fragmentUri.queryParameters['token'];
     } catch (e) {
       print("Error parsing URL fragment: $e");
     }
  }
  
  if (token != null && token.isNotEmpty) {
    // print("🔹 [Google Auth] Token found: ${token.substring(0, 10)}...");
    
    // 1. Save Token
    const storage = FlutterSecureStorage();
    await storage.write(key: 'auth_token', value: token); 
    
    // 2. The App Router (UserController) will pick this up on load and auto-login.
  }
  // ----------------------------------------------------

  runApp(const ProviderScope(child: MDQApp()));
}

class MDQApp extends ConsumerWidget {
  const MDQApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final goRouter = ref.watch(goRouterProvider);

    // 1. Listen to the active user state (updates when you toggle settings)
    final activeUser = ref.watch(userControllerProvider).value;

    // 2. Listen to the database fetch (updates when app restarts)
    final fetchedUser = ref.watch(userProvider).value;

    // 3. Merge them (Active takes priority)
    final User? currentUser = activeUser ?? fetchedUser;

    // 4. Determine Theme
    ThemeMode currentMode = ThemeMode.light;
    if (currentUser != null && currentUser.settingsTheme == 'dark') {
      currentMode = ThemeMode.dark;
    }

    return MaterialApp.router(
      title: 'MDQ+',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.lightTheme,
      darkTheme: AppTheme.darkTheme,
      themeMode: currentMode,
      routerConfig: goRouter,
    );
  }
}
