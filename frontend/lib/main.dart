import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart'; // Import storage
import 'src/core/router/app_router.dart';
import 'src/core/theme/app_theme.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // --- ☢️ NUCLEAR WIPE: Fixes the 401 Loop ---
  // This deletes the "Ghost Token" so you can log in fresh.
  const storage = FlutterSecureStorage();
  await storage.deleteAll();
  debugPrint("💥 STORAGE WIPED: You are logged out. 💥");
  // -------------------------------------------------------

  runApp(const ProviderScope(child: MedIQApp()));
}

class MedIQApp extends ConsumerWidget {
  const MedIQApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final goRouter = ref.watch(goRouterProvider);

    return MaterialApp.router(
      title: 'MDQplus',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.lightTheme,
      themeMode: ThemeMode.light,
      routerConfig: goRouter,
    );
  }
}
