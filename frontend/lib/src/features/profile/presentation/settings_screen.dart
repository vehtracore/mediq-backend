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
  // ── General settings state ────────────────────────────────────────────────
  late bool _isDarkMode;
  late bool _notifications;
  late bool _emailUpdates;

  // ── Emergency / NOK state ─────────────────────────────────────────────────
  late TextEditingController _nokController;
  bool _smsEnabled  = false;
  bool _nokSaving   = false;
  bool _nokInitialized = false;

  @override
  void initState() {
    super.initState();
    final user = ref.read(userProvider).value;
    _isDarkMode   = (user?.settingsTheme == 'dark');
    _notifications = user?.settingsNotifications ?? true;
    _emailUpdates  = user?.settingsEmailUpdates ?? false;

    // Initialize controller with persisted value from the server
    _nokController = TextEditingController(text: user?.kinPhone ?? '');
    _smsEnabled    = user?.emergencySmsEnabled ?? false;
    _nokInitialized = true;
  }

  @override
  void dispose() {
    _nokController.dispose();
    super.dispose();
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  bool get _isPremium {
    final user = ref.read(userProvider).value;
    return user?.isPremium ?? false;
  }

  /// Saves general toggles (theme / notifications / email)
  Future<void> _updateSetting(String key, bool value) async {
    setState(() {
      if (key == 'theme')  _isDarkMode   = value;
      if (key == 'notify') _notifications = value;
      if (key == 'email')  _emailUpdates  = value;
    });
    try {
      await ref.read(authControllerProvider.notifier).updateProfile(
            settingsTheme:         key == 'theme'  ? (value ? 'dark' : 'light') : null,
            settingsNotifications: key == 'notify' ? value : null,
            settingsEmailUpdates:  key == 'email'  ? value : null,
          );
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Failed to save setting.')),
        );
      }
    }
  }

  /// Saves the NOK phone + toggle state to the backend.
  Future<void> _saveNokSettings() async {
    final phone = _nokController.text.trim();
    if (phone.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Please enter a valid phone number.'),
          backgroundColor: Color(0xFFE53935),
          behavior: SnackBarBehavior.floating,
        ),
      );
      return;
    }

    setState(() => _nokSaving = true);
    try {
      await ref.read(authControllerProvider.notifier).updateProfile(
            kinPhone:             phone,
            emergencySmsEnabled:  _smsEnabled,
          );
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Emergency settings saved ✅'),
            backgroundColor: Color(0xFF2E7D32),
            behavior: SnackBarBehavior.floating,
          ),
        );
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Failed to save. Please try again.'),
            backgroundColor: Color(0xFFE53935),
            behavior: SnackBarBehavior.floating,
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _nokSaving = false);
    }
  }

  // ── Build ─────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final theme  = Theme.of(context);
    final isPremium = _isPremium;
    final user = ref.read(userProvider).value;

    return Scaffold(
      backgroundColor: theme.scaffoldBackgroundColor,
      appBar: AppBar(
        title: Text('Settings', style: theme.textTheme.titleLarge),
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
          _buildSectionHeader('Preferences'),
          _buildSwitchTile('Dark Mode', _isDarkMode,
              (v) => _updateSetting('theme', v), Icons.dark_mode_outlined),
          const SizedBox(height: 8),
          _buildSwitchTile('Push Notifications', _notifications,
              (v) => _updateSetting('notify', v), Icons.notifications_outlined),
          const SizedBox(height: 8),
          _buildSwitchTile('Email Updates', _emailUpdates,
              (v) => _updateSetting('email', v), Icons.email_outlined),

          const SizedBox(height: 24),

          // ── Emergency Protocol section ──────────────────────────────────
          if (user?.role == 'patient') ...[
            _buildSectionHeader('Emergency Protocol'),
            _buildEmergencySection(theme, isPremium),
            const SizedBox(height: 24),
          ],

          _buildSectionHeader('Account'),
          _buildActionTile('Delete Account', Icons.delete_forever, () {
            showDialog(
              context: context,
              builder: (_) => const DeleteAccountDialog(),
            );
          }, color: Colors.red),
        ],
      ),
    );
  }

  // ── Emergency Section ─────────────────────────────────────────────────────

  Widget _buildEmergencySection(ThemeData theme, bool isPremium) {
    final isDark = theme.brightness == Brightness.dark;
    const accent = Color(0xFF4A90E2);
    final cardColor = theme.cardTheme.color ?? (isDark ? const Color(0xFF1E2A3A) : Colors.white);
    final subtleText = isDark ? Colors.white54 : Colors.grey[600];
    final shadow = isDark ? <BoxShadow>[] : [BoxShadow(color: Colors.grey.withOpacity(0.05), blurRadius: 4)];

    return Container(
      decoration: BoxDecoration(
        color: cardColor,
        borderRadius: BorderRadius.circular(16),
        boxShadow: shadow,
      ),
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header row
          Row(children: [
            const Icon(Icons.health_and_safety_rounded, color: Color(0xFF4A90E2), size: 20),
            const SizedBox(width: 8),
            Text('Next of Kin Alerts',
                style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
          ]),
          const SizedBox(height: 12),

          // ── Premium gate ───────────────────────────────────────────────
          if (!isPremium) ...[
            // Greyed-out locked input
            AbsorbPointer(
              child: Opacity(
                opacity: 0.4,
                child: _nokInputField(theme, cardColor, enabled: false),
              ),
            ),
            const SizedBox(height: 12),
            // Upgrade banner
            GestureDetector(
              onTap: () => context.push('/subscription'),
              child: Container(
                width: double.infinity,
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                decoration: BoxDecoration(
                  gradient: const LinearGradient(
                    colors: [Color(0xFF4A90E2), Color(0xFF1565C0)],
                    begin: Alignment.centerLeft, end: Alignment.centerRight,
                  ),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Row(children: [
                  const Icon(Icons.lock_rounded, color: Colors.white, size: 16),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'Emergency Next-of-Kin alerts require Premium',
                      style: const TextStyle(
                          color: Colors.white, fontSize: 13, fontWeight: FontWeight.w600),
                    ),
                  ),
                  const SizedBox(width: 8),
                  const Text('Upgrade →',
                      style: TextStyle(
                          color: Colors.white, fontSize: 12, fontWeight: FontWeight.bold)),
                ]),
              ),
            ),
          ]

          // ── Premium: full NOK form ─────────────────────────────────────
          else ...[
            _nokInputField(theme, cardColor, enabled: true),
            const SizedBox(height: 16),

            // SMS toggle
            _buildInlineToggle(
              icon: Icons.sms_outlined,
              label: 'SMS Alert',
              value: _smsEnabled,
              onChanged: (v) => setState(() => _smsEnabled = v),
              theme: theme,
              subtleText: subtleText,
            ),
            const SizedBox(height: 20),

            // Save button
            SizedBox(
              width: double.infinity, height: 48,
              child: ElevatedButton(
                onPressed: _nokSaving ? null : _saveNokSettings,
                style: ElevatedButton.styleFrom(
                  backgroundColor: accent,
                  disabledBackgroundColor: accent.withOpacity(0.5),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                  elevation: 0,
                ),
                child: _nokSaving
                    ? const SizedBox(width: 20, height: 20,
                        child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                    : const Text('Save Emergency Settings',
                        style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _nokInputField(ThemeData theme, Color cardColor, {required bool enabled}) {
    return TextField(
      controller: _nokController,
      enabled: enabled,
      keyboardType: TextInputType.phone,
      style: theme.textTheme.bodyLarge,
      decoration: InputDecoration(
        labelText: 'Next of Kin Phone Number',
        hintText: '+2348012345678',
        prefixIcon: const Icon(Icons.contact_phone_outlined, color: Color(0xFF4A90E2)),
        filled: true,
        fillColor: cardColor,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide.none,
        ),
        contentPadding: const EdgeInsets.symmetric(vertical: 14, horizontal: 12),
      ),
    );
  }

  Widget _buildInlineToggle({
    required IconData icon,
    required String label,
    required bool value,
    required ValueChanged<bool> onChanged,
    required ThemeData theme,
    required Color? subtleText,
  }) {
    return Row(children: [
      Icon(icon, color: const Color(0xFF4A90E2), size: 20),
      const SizedBox(width: 10),
      Expanded(child: Text(label, style: theme.textTheme.bodyMedium)),
      Switch(
        value: value,
        onChanged: onChanged,
        activeColor: const Color(0xFF4A90E2),
      ),
    ]);
  }

  // ── Generic tile builders ─────────────────────────────────────────────────

  Widget _buildSectionHeader(String title) {
    return Padding(
      padding: const EdgeInsets.only(left: 8, bottom: 8),
      child: Text(title,
          style: const TextStyle(
              fontWeight: FontWeight.bold, color: Colors.grey, fontSize: 14)),
    );
  }

  Widget _buildSwitchTile(
      String title, bool value, Function(bool) onChanged, IconData icon) {
    final theme = Theme.of(context);
    return Container(
      decoration: BoxDecoration(
        color: theme.cardTheme.color,
        borderRadius: BorderRadius.circular(12),
        boxShadow: theme.brightness == Brightness.dark
            ? []
            : [BoxShadow(color: Colors.grey.withOpacity(0.05), blurRadius: 4)],
      ),
      child: SwitchListTile(
        secondary: Icon(icon, color: const Color(0xFF4A90E2)),
        title: Text(title, style: theme.textTheme.bodyLarge),
        value: value,
        onChanged: onChanged,
        activeColor: const Color(0xFF4A90E2),
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
