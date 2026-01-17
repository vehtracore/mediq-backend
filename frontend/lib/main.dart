import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'src/core/router/app_router.dart';
import 'src/core/theme/app_theme.dart';
import 'src/features/auth/presentation/user_controller.dart';
import 'src/features/auth/data/user_model.dart';

void main() {
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
