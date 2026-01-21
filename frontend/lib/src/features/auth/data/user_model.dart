import 'package:mediq_app/src/core/api/api_constants.dart'; // Ensure you have your base URL here

class User {
  final String id;
  final String email;
  final String firstName;
  final String lastName;
  final String role;
  final String subscriptionTier;
  final String imageUrl; // ✅ This will now ALWAYS be a full URL
  final String? location;

  // Medical
  final String? bloodType;
  final String? allergies;
  final String? chronicConditions;
  final String? medications;
  final String? pastSurgeries;

  // Settings
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
    // 1. EXTRACT Raw Image Path
    String? rawImage = json['image_url'] ?? json['profile_image'];

    // 2. SANITIZE: Ensure it is a full URL
    String finalUrl = '';
    if (rawImage != null && rawImage.isNotEmpty) {
      if (rawImage.startsWith('http')) {
        finalUrl = rawImage;
      } else {
        // If backend sends distinct path (e.g. "uploads/x.jpg"), prepend Base URL
        // We strip any leading slash to avoid double slashes
        final cleanPath = rawImage.startsWith('/') ? rawImage.substring(1) : rawImage;
        // NOTE: Replace this string with your actual backend URL variable if available
        finalUrl = "http://127.0.0.1:8000/$cleanPath"; 
      }
    }

    return User(
      id: json['id'].toString(),
      email: json['email'] ?? '',
      firstName: json['first_name'] ?? '',
      lastName: json['last_name'] ?? '',
      role: json['role'] ?? 'patient',
      subscriptionTier: json['subscription_tier'] ?? 'free',
      imageUrl: finalUrl, // ✅ Assign Sanitized URL
      location: json['location'],

      bloodType: json['blood_type'],
      allergies: json['allergies'],
      chronicConditions: json['chronic_conditions'],
      medications: json['medications'],
      pastSurgeries: json['past_surgeries'],

      settingsTheme: json['settings_theme'] ?? 'light',
      settingsNotifications: json['settings_notifications'] ?? true,
      settingsEmailUpdates: json['settings_email_updates'] ?? false,
    );
  }

  // ... toJson() remains the same ...
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