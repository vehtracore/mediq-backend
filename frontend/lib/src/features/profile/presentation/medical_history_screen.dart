import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/features/auth/presentation/auth_controller.dart';
import 'package:mediq_app/src/features/auth/presentation/user_controller.dart';

class MedicalHistoryScreen extends ConsumerStatefulWidget {
  const MedicalHistoryScreen({super.key});

  @override
  ConsumerState<MedicalHistoryScreen> createState() =>
      _MedicalHistoryScreenState();
}

class _MedicalHistoryScreenState extends ConsumerState<MedicalHistoryScreen> {
  final _bloodTypeCtrl = TextEditingController();
  final _allergiesCtrl = TextEditingController();
  final _conditionsCtrl = TextEditingController();
  final _medicationsCtrl = TextEditingController();
  final _surgeriesCtrl = TextEditingController();

  @override
  void initState() {
    super.initState();
    final user = ref.read(userProvider).value;
    if (user != null) {
      _bloodTypeCtrl.text = user.bloodType ?? '';
      _allergiesCtrl.text = user.allergies ?? '';
      _conditionsCtrl.text = user.chronicConditions ?? '';
      _medicationsCtrl.text = user.medications ?? '';
      _surgeriesCtrl.text = user.pastSurgeries ?? '';
    }
  }

  @override
  void dispose() {
    _bloodTypeCtrl.dispose();
    _allergiesCtrl.dispose();
    _conditionsCtrl.dispose();
    _medicationsCtrl.dispose();
    _surgeriesCtrl.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    try {
      await ref.read(authControllerProvider.notifier).updateProfile(
            bloodType: _bloodTypeCtrl.text.trim(),
            allergies: _allergiesCtrl.text.trim(),
            chronicConditions: _conditionsCtrl.text.trim(),
            medications: _medicationsCtrl.text.trim(),
            pastSurgeries: _surgeriesCtrl.text.trim(),
          );
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
              content: Text("Medical History Saved!"),
              backgroundColor: Colors.green),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text("Error: $e"), backgroundColor: Colors.red),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final isLoading = ref.watch(authControllerProvider).isLoading;
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;

    return Scaffold(
      backgroundColor: theme.scaffoldBackgroundColor, // ✅ Dynamic
      appBar: AppBar(
        title: Text("Medical History", style: theme.textTheme.titleLarge),
        backgroundColor: theme.appBarTheme.backgroundColor,
        elevation: 0,
        iconTheme: theme.iconTheme,
        actions: [
          TextButton(
            onPressed: isLoading ? null : _save,
            child: isLoading
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2))
                : const Text("Save",
                    style:
                        TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
          )
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          children: [
            _buildCard("Blood Type", "e.g., O+, A-", _bloodTypeCtrl,
                icon: Icons.bloodtype, theme: theme, isDark: isDark),
            _buildCard("Allergies", "e.g., Peanuts, Penicillin", _allergiesCtrl,
                icon: Icons.warning_amber, theme: theme, isDark: isDark),
            _buildCard(
                "Chronic Conditions", "e.g., Asthma, Diabetes", _conditionsCtrl,
                icon: Icons.healing, theme: theme, isDark: isDark),
            _buildCard("Current Medications", "e.g., Ibuprofen 200mg",
                _medicationsCtrl,
                icon: Icons.medication, theme: theme, isDark: isDark),
            _buildCard(
                "Past Surgeries", "e.g., Appendectomy (2015)", _surgeriesCtrl,
                icon: Icons.content_cut, theme: theme, isDark: isDark),
          ],
        ),
      ),
    );
  }

  Widget _buildCard(String label, String hint, TextEditingController ctrl,
      {required IconData icon,
      required ThemeData theme,
      required bool isDark}) {
    return Container(
      margin: const EdgeInsets.only(bottom: 16),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: theme.cardTheme.color, // ✅ Dynamic Card
        borderRadius: BorderRadius.circular(12),
        boxShadow: isDark
            ? []
            : [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 5)],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, color: Colors.blueAccent, size: 20),
              const SizedBox(width: 8),
              Text(label,
                  style: theme.textTheme.bodyLarge?.copyWith(
                      fontWeight: FontWeight.bold, fontSize: 16)), // ✅ Dynamic
            ],
          ),
          const SizedBox(height: 12),
          TextField(
            controller: ctrl,
            style: theme.textTheme.bodyLarge, // ✅ Dynamic Input
            decoration: InputDecoration(
              hintText: hint,
              hintStyle: TextStyle(
                  color: isDark ? Colors.grey[500] : Colors.grey[400]),
              border:
                  OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
              contentPadding:
                  const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
              fillColor: theme.inputDecorationTheme.fillColor,
              filled: true,
            ),
            maxLines: null,
          ),
        ],
      ),
    );
  }
}
