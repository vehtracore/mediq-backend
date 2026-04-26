import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:mediq_app/src/features/auth/presentation/auth_controller.dart';
import 'package:mediq_app/src/features/auth/presentation/user_controller.dart';
import '../../../shared/presentation/widgets/delete_account_dialog.dart';

class SettingsScreen extends ConsumerStatefulWidget {
  const SettingsScreen({super.key});

  @override
  ConsumerState<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends ConsumerState<SettingsScreen> {
  late bool _isDarkMode;
  late bool _notifications;
  late bool _emailUpdates;

  String _nokPhone = '';
  bool _pushEnabled = false;
  bool _termSmsEnabled = false;
  bool _termVoiceEnabled = false;

  @override
  void initState() {
    super.initState();
    final user = ref.read(userProvider).value;
    _isDarkMode = (user?.settingsTheme == 'dark');
    _notifications = user?.settingsNotifications ?? true;
    _emailUpdates = user?.settingsEmailUpdates ?? false;
  }

  Future<void> _updateSetting(String key, bool value) async {
    setState(() {
      if (key == 'theme') _isDarkMode = value;
      if (key == 'notify') _notifications = value;
      if (key == 'email') _emailUpdates = value;
    });

    try {
      await ref.read(authControllerProvider.notifier).updateProfile(
            settingsTheme: key == 'theme' ? (value ? 'dark' : 'light') : null,
            settingsNotifications: key == 'notify' ? value : null,
            settingsEmailUpdates: key == 'email' ? value : null,
          );
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(const SnackBar(content: Text("Failed to save")));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    // 1. Get current theme colors
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;

    return Scaffold(
      // 2. Use Theme Background
      backgroundColor: theme.scaffoldBackgroundColor,
      appBar: AppBar(
        title: Text("Settings", style: theme.textTheme.titleLarge),
        backgroundColor: theme.appBarTheme.backgroundColor,
        elevation: 0,
        leading: IconButton(
          icon: Icon(Icons.arrow_back, color: theme.iconTheme.color),
          onPressed: () => context.pop(),
        ),
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _buildSectionHeader("Preferences"),
          _buildSwitchTile("Dark Mode", _isDarkMode,
              (v) => _updateSetting('theme', v), Icons.dark_mode_outlined),
          const SizedBox(height: 8),
          _buildSwitchTile("Push Notifications", _notifications,
              (v) => _updateSetting('notify', v), Icons.notifications_outlined),
          const SizedBox(height: 8),
          _buildSwitchTile("Email Updates", _emailUpdates,
              (v) => _updateSetting('email', v), Icons.email_outlined),
          const SizedBox(height: 24),
          ExpansionTile(
            title: const Text('Emergency Protocol', style: TextStyle(fontWeight: FontWeight.bold)),
            leading: Icon(Icons.health_and_safety, color: theme.iconTheme.color),
            childrenPadding: const EdgeInsets.only(left: 16, right: 16, bottom: 16),
            children: [
              _buildTextFieldCard(),
              const SizedBox(height: 16),
              _buildSwitchTile("In-App Push Notification (Free)", _pushEnabled,
                  (v) => setState(() => _pushEnabled = v), Icons.notifications_active_outlined),
              const SizedBox(height: 16),
              _buildSwitchTile("SMS Alert", _termSmsEnabled,
                  (v) => setState(() => _termSmsEnabled = v), Icons.sms_outlined),
              const SizedBox(height: 16),
              _buildSwitchTile("Automated Voice Call", _termVoiceEnabled,
                  (v) => setState(() => _termVoiceEnabled = v), Icons.phone_in_talk_outlined),
            ],
          ),
          const SizedBox(height: 24),
          _buildSectionHeader("Account"),
          _buildActionTile("Delete Account", Icons.delete_forever, () {
            showDialog(
              context: context,
              builder: (context) => const DeleteAccountDialog(),
            );
          }, color: Colors.red),
        ],
      ),
    );
  }

  Widget _buildSectionHeader(String title) {
    return Padding(
      padding: const EdgeInsets.only(left: 8, bottom: 8),
      child: Text(title,
          style: const TextStyle(
              fontWeight: FontWeight.bold, color: Colors.grey, fontSize: 14)),
    );
  }

  Widget _buildTextFieldCard() {
    final theme = Theme.of(context);
    return Container(
      decoration: BoxDecoration(
        color: theme.cardTheme.color,
        borderRadius: BorderRadius.circular(12),
        boxShadow: theme.brightness == Brightness.dark
            ? []
            : [BoxShadow(color: Colors.grey.withOpacity(0.05), blurRadius: 4)],
      ),
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
      child: TextFormField(
        initialValue: _nokPhone,
        keyboardType: TextInputType.phone,
        style: theme.textTheme.bodyLarge,
        decoration: const InputDecoration(
          labelText: "Next of Kin Phone Number",
          border: InputBorder.none,
          icon: Icon(Icons.contact_phone_outlined, color: Color(0xFF4A90E2)),
        ),
        onChanged: (val) {
          setState(() {
            _nokPhone = val;
          });
        },
      ),
    );
  }

  Widget _buildSwitchTile(
      String title, bool value, Function(bool) onChanged, IconData icon) {
    final theme = Theme.of(context);
    return Container(
      decoration: BoxDecoration(
        // 3. Dynamic Card Color
        color: theme.cardTheme.color,
        borderRadius: BorderRadius.circular(12),
        // Hide shadow in dark mode for cleaner look
        boxShadow: theme.brightness == Brightness.dark
            ? []
            : [BoxShadow(color: Colors.grey.withOpacity(0.05), blurRadius: 4)],
      ),
      child: SwitchListTile(
        secondary: Icon(icon, color: const Color(0xFF4A90E2)),
        title: Text(title, style: theme.textTheme.bodyLarge),
        value: value,
        onChanged: onChanged,
        activeThumbColor: const Color(0xFF4A90E2),
      ),
    );
  }

  Widget _buildActionTile(String title, IconData icon, VoidCallback onTap,
      {Color? color}) {
    final theme = Theme.of(context);
    return Container(
      decoration: BoxDecoration(
        color: theme.cardTheme.color,
        borderRadius: BorderRadius.circular(12),
        boxShadow: theme.brightness == Brightness.dark
            ? []
            : [BoxShadow(color: Colors.grey.withOpacity(0.05), blurRadius: 4)],
      ),
      child: ListTile(
        leading: Icon(icon, color: color ?? theme.iconTheme.color),
        title: Text(title,
            style: theme.textTheme.bodyLarge?.copyWith(color: color)),
        trailing: const Icon(Icons.chevron_right, color: Colors.grey),
        onTap: onTap,
      ),
    );
  }
}
