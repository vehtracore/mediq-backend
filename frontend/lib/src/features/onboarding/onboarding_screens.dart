import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

// --- Onboarding Screen ---
class OnboardingScreen extends StatelessWidget {
  const OnboardingScreen({super.key});
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(
              Icons.medical_services,
              size: 80,
              color: Color(0xFF4A90E2),
            ),
            const SizedBox(height: 20),
            const Text(
              "Welcome to MDQ+",
              style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 10),
            const Text("AI-Powered Healthcare at your fingertips"),
            const SizedBox(height: 40),
            ElevatedButton(
              onPressed: () => context.go('/safety_disclaimer'),
              child: const Text("Get Started"),
            ),
          ],
        ),
      ),
    );
  }
}

// --- Safety Disclaimer Screen ---
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
            ),
            const SizedBox(height: 32),
            const Text(
              "Safety First",
              style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 16),
            const Text(
              "MDQ+ AI provides triage suggestions but does not replace professional medical advice. In emergencies, always call 112 or go to a hospital.",
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 16),
            ),
            const SizedBox(height: 40),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: () => context.go('/auth'),
                child: const Text("I Understand & Agree"),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
