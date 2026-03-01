import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'src/core/router/app_router.dart';
import 'src/core/theme/app_theme.dart';
import 'src/features/auth/presentation/user_controller.dart';
import 'src/features/auth/data/user_model.dart';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
// import 'package:web/web.dart' as web; // For cleaning URL (Optional)

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

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
