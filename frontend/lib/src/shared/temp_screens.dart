import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

// --- 1. Onboarding ---
class OnboardingScreen extends StatelessWidget {
  const OnboardingScreen({super.key});
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: ElevatedButton(
          onPressed: () => context.go('/safety_disclaimer'),
          child: const Text("Skip to Safety"),
        ),
      ),
    );
  }
}

// --- 2. Safety Disclaimer (CRITICAL) ---
class SafetyDisclaimerScreen extends StatelessWidget {
  const SafetyDisclaimerScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Padding(
        padding: const EdgeInsets.all(24.0),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(
              Icons.shield_outlined,
              size: 100,
              color: Color(0xFF50E3C2),
            ), // Safety Shield
            const SizedBox(height: 32),
            Text(
              "AI Safety Disclaimer",
              style: Theme.of(context).textTheme.displayMedium,
            ),
            const SizedBox(height: 16),
            Text(
              "MedIQ AI provides triage suggestions but does not replace professional medical advice. For emergencies, consult a doctor",
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.bodyLarge,
            ),
            const Spacer(),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: () => context.go('/auth'),
                child: const Text("Agree & Continue"),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// --- 3. Doctor Home ---
class DoctorHomeScreen extends StatelessWidget {
  const DoctorHomeScreen({super.key});
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text("Doctor Dashboard")),
      backgroundColor: const Color(0xFF4A90E2).withOpacity(0.05),
      body: const Center(child: Text("Doctor Content")),
    );
  }
}
