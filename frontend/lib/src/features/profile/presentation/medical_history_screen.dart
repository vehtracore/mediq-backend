import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
// ✅ These imports were missing:
import 'package:mediq_app/src/features/auth/presentation/auth_controller.dart';
import 'package:mediq_app/src/features/auth/presentation/user_controller.dart';

class MedicalHistoryScreen extends ConsumerStatefulWidget {
  const MedicalHistoryScreen({super.key});

  @override
  ConsumerState<MedicalHistoryScreen> createState() => _MedicalHistoryScreenState();
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

  Future<void> _save() async {
    try {
      await ref.read(authControllerProvider.notifier).updateProfile(
            bloodType: _bloodTypeCtrl.text.trim(),
            allergies: _allergiesCtrl.text.trim(),
            chronicConditions: _conditionsCtrl.text.trim(),
            medications: _medicationsCtrl.text.trim(),
            pastSurgeries: _surgeriesCtrl.text.trim(),
          );
      
      ref.invalidate(userProvider);

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text("Medical History Saved!"), backgroundColor: Colors.green),
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
      backgroundColor: theme.scaffoldBackgroundColor,
      appBar: AppBar(
        title: Text("Medical History", style: theme.textTheme.titleLarge),
        backgroundColor: theme.appBarTheme.backgroundColor,
        actions: [
          TextButton(
            onPressed: isLoading ? null : _save,
            child: isLoading
                ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
                : const Text("Save", style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
          )
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          children: [
            _buildCard("Blood Type", "e.g., O+, A-", _bloodTypeCtrl, theme, isDark),
            _buildCard("Allergies", "e.g., Peanuts, Penicillin", _allergiesCtrl, theme, isDark),
            _buildCard("Chronic Conditions", "e.g., Asthma", _conditionsCtrl, theme, isDark),
            _buildCard("Current Medications", "e.g., Ibuprofen", _medicationsCtrl, theme, isDark),
            _buildCard("Past Surgeries", "e.g., Appendectomy", _surgeriesCtrl, theme, isDark),
          ],
        ),
      ),
    );
  }

  Widget _buildCard(String label, String hint, TextEditingController ctrl, ThemeData theme, bool isDark) {
    return Container(
      margin: const EdgeInsets.only(bottom: 16),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: theme.cardTheme.color,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: theme.textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.bold)),
          const SizedBox(height: 12),
          TextField(
            controller: ctrl,
            style: theme.textTheme.bodyLarge,
            decoration: InputDecoration(
              hintText: hint,
              filled: true,
              fillColor: theme.inputDecorationTheme.fillColor,
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
            ),
          ),
        ],
      ),
    );
  }
}