import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  bool _isDarkMode = false;
  bool _pushNotifications = true;
  bool _emailUpdates = false;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF9FAFB),
      appBar: AppBar(
        title: const Text(
          "Settings",
          style: TextStyle(color: Colors.black, fontWeight: FontWeight.bold),
        ),
        backgroundColor: Colors.white,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back, color: Colors.black),
          onPressed: () => context.pop(),
        ),
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _buildSectionHeader("Preferences"),
          _buildSwitchTile(
            "Dark Mode",
            _isDarkMode,
            (v) => setState(() => _isDarkMode = v),
            Icons.dark_mode_outlined,
          ),
          const SizedBox(height: 8),
          _buildSwitchTile(
            "Push Notifications",
            _pushNotifications,
            (v) => setState(() => _pushNotifications = v),
            Icons.notifications_outlined,
          ),
          const SizedBox(height: 8),
          _buildSwitchTile(
            "Email Updates",
            _emailUpdates,
            (v) => setState(() => _emailUpdates = v),
            Icons.email_outlined,
          ),

          const SizedBox(height: 24),
          _buildSectionHeader("Account"),
          _buildActionTile("Change Password", Icons.lock_outline, () {}),
          const SizedBox(height: 8),
          _buildActionTile("Language", Icons.language, () {}),

          const SizedBox(height: 24),
          _buildSectionHeader("Support"),
          _buildActionTile("Help Center", Icons.help_outline, () {}),
          const SizedBox(height: 8),
          _buildActionTile("Privacy Policy", Icons.privacy_tip_outlined, () {}),
          const SizedBox(height: 8),
          _buildActionTile(
            "Terms of Service",
            Icons.description_outlined,
            () {},
          ),

          const SizedBox(height: 32),
          ListTile(
            tileColor: Colors.red.withOpacity(0.1),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(12),
            ),
            leading: const Icon(Icons.delete_forever, color: Colors.red),
            title: const Text(
              "Delete Account",
              style: TextStyle(color: Colors.red, fontWeight: FontWeight.bold),
            ),
            onTap: () => _showDeleteDialog(context),
          ),
        ],
      ),
    );
  }

  Widget _buildSectionHeader(String title) {
    return Padding(
      padding: const EdgeInsets.only(left: 8, bottom: 8),
      child: Text(
        title,
        style: const TextStyle(
          fontWeight: FontWeight.bold,
          color: Colors.grey,
          fontSize: 14,
        ),
      ),
    );
  }

  Widget _buildSwitchTile(
    String title,
    bool value,
    Function(bool) onChanged,
    IconData icon,
  ) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        boxShadow: [
          BoxShadow(
            color: Colors.grey.withOpacity(0.05),
            blurRadius: 4,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      child: SwitchListTile(
        secondary: Icon(icon, color: const Color(0xFF4A90E2)),
        title: Text(title, style: const TextStyle(fontWeight: FontWeight.w500)),
        value: value,
        onChanged: onChanged,
        activeColor: const Color(0xFF4A90E2),
      ),
    );
  }

  Widget _buildActionTile(String title, IconData icon, VoidCallback onTap) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        boxShadow: [
          BoxShadow(
            color: Colors.grey.withOpacity(0.05),
            blurRadius: 4,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      child: ListTile(
        leading: Icon(icon, color: Colors.grey[600]),
        title: Text(title, style: const TextStyle(fontWeight: FontWeight.w500)),
        trailing: const Icon(Icons.chevron_right, color: Colors.grey),
        onTap: onTap,
      ),
    );
  }

  void _showDeleteDialog(BuildContext context) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text("Delete Account?"),
        content: const Text("This action is irreversible."),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text("Cancel"),
          ),
          TextButton(
            onPressed: () {
              Navigator.pop(ctx);
              context.go('/auth');
            },
            child: const Text("Delete", style: TextStyle(color: Colors.red)),
          ),
        ],
      ),
    );
  }
}
