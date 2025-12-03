
import 'package:flutter/material.dart';
class MedicalHistoryScreen extends StatelessWidget {
  const MedicalHistoryScreen({super.key});
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF9FAFB),
      appBar: AppBar(title: const Text("Medical History", style: TextStyle(color: Colors.black)), backgroundColor: Colors.white, elevation: 0, iconTheme: const IconThemeData(color: Colors.black)),
      body: Center(child: Text("No history yet", style: TextStyle(color: Colors.grey[500]))),
    );
  }
}
