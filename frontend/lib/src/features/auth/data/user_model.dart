import 'package:mediq_app/src/features/auth/data/user_model.dart'; // Ensure correct path if needed

class User {
  final String id;
  final String email;
  final String firstName;
  final String lastName;
  final String role;
  final String subscriptionTier;
  final String imageUrl; // ✅ Sanitized URL
  final String? location;

  // --- 🏥 Medical History ---
  final String? bloodType;
  final String? allergies;
  final String? chronicConditions;
  final String? medications;
  final String? pastSurgeries;

  // --- ⚙️ Settings ---
  final String settingsTheme;
  final bool settingsNotifications;
  final bool settingsEmailUpdates;

  User({
    required this.id,
    required this.email,
    required this.firstName,
    required this.lastName,
    required this.role,
    this.subscriptionTier = 'free',
    this.imageUrl = '',
    this.location,
    this.bloodType,
    this.allergies,
    this.chronicConditions,
    this.medications,
    this.pastSurgeries,
    this.settingsTheme = 'light',
    this.settingsNotifications = true,
    this.settingsEmailUpdates = false,
  });

  factory User.fromJson(Map<String, dynamic> json) {
    // 1. Get raw path
    String rawImage = json['image_url'] ?? json['profile_image'] ?? '';
    
    // 2. Fix URL for Render
    String finalUrl = '';
    if (rawImage.isNotEmpty) {
      if (rawImage.startsWith('http')) {
        finalUrl = rawImage;
      } else {
        // ✅ REAL RENDER URL from your screenshot
        const baseUrl = "https://mediq-backend-m3ik.onrender.com"; 
        
        final cleanPath = rawImage.startsWith('/') ? rawImage.substring(1) : rawImage;
        finalUrl = "$baseUrl/$cleanPath";
      }
    }

    return User(
      id: (json['id'] ?? '').toString(),
      email: json['email'] ?? '',
      firstName: json['first_name'] ?? json['firstName'] ?? '',
      lastName: json['last_name'] ?? json['lastName'] ?? '',
      role: json['role'] ?? 'patient',
      subscriptionTier: json['subscription_tier'] ?? json['plan'] ?? 'free',
      imageUrl: finalUrl, // ✅ Sanitized
      location: json['location'],

      // Map new fields
      bloodType: json['blood_type'],
      allergies: json['allergies'],
      chronicConditions: json['chronic_conditions'],
      medications: json['medications'],
      pastSurgeries: json['past_surgeries'],

      // Settings
      settingsTheme: json['settings_theme'] ?? 'light',
      settingsNotifications: json['settings_notifications'] ?? true,
      settingsEmailUpdates: json['settings_email_updates'] ?? false,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'email': email,
      'first_name': firstName,
      'last_name': lastName,
      'role': role,
      'subscription_tier': subscriptionTier,
      'image_url': imageUrl,
      'location': location,
      'blood_type': bloodType,
      'allergies': allergies,
      'chronic_conditions': chronicConditions,
      'medications': medications,
      'past_surgeries': pastSurgeries,
      'settings_theme': settingsTheme,
      'settings_notifications': settingsNotifications,
      'settings_email_updates': settingsEmailUpdates,
    };
  }
}