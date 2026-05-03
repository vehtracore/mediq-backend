class User {
  final String id;
  final String email;
  final String firstName;
  final String lastName;
  final String role;
  final String subscriptionTier;
  final String imageUrl; // ✅ Sanitized URL
  final String? location;
  final bool isBanned;

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

  // --- 🚨 Emergency ---
  final String? kinPhone;           // Next of Kin phone in international format
  final bool emergencySmsEnabled;

  User({
    required this.id,
    required this.email,
    required this.firstName,
    required this.lastName,
    required this.role,
    this.subscriptionTier = 'free',
    this.imageUrl = '',
    this.location,
    this.isBanned = false,
    this.bloodType,
    this.allergies,
    this.chronicConditions,
    this.medications,
    this.pastSurgeries,
    this.settingsTheme = 'light',
    this.settingsNotifications = true,
    this.settingsEmailUpdates = false,
    this.kinPhone,
    this.emergencySmsEnabled = false,
  });

  factory User.fromJson(Map<String, dynamic> json) {
    // 1. EXTRACT Raw Image Path
    String rawImage = json['image_url'] ?? json['profile_image'] ?? '';

    // 2. SANITIZE: Force valid Render URL
    String finalUrl = '';
    if (rawImage.isNotEmpty) {
      if (rawImage.startsWith('http')) {
        finalUrl = rawImage;
      } else {
        // ✅ YOUR REAL BACKEND URL
        const String baseUrl = "https://mediq-backend-m3ik.onrender.com"; 
        
        // Strip leading slash if present
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
      imageUrl: finalUrl,
      location: json['location'],
      isBanned: json['is_banned'] ?? false,

      bloodType: json['blood_type'],
      allergies: json['allergies'],
      chronicConditions: json['chronic_conditions'],
      medications: json['medications'],
      pastSurgeries: json['past_surgeries'],

      settingsTheme: json['settings_theme'] ?? 'light',
      settingsNotifications: json['settings_notifications'] ?? true,
      settingsEmailUpdates: json['settings_email_updates'] ?? false,
      kinPhone: json['kin_phone'],
      emergencySmsEnabled: json['emergency_sms_enabled'] ?? false,
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
      'is_banned': isBanned,
      'blood_type': bloodType,
      'allergies': allergies,
      'chronic_conditions': chronicConditions,
      'medications': medications,
      'past_surgeries': pastSurgeries,
      'settings_theme': settingsTheme,
      'settings_notifications': settingsNotifications,
      'settings_email_updates': settingsEmailUpdates,
      'kin_phone': kinPhone,
      'emergency_sms_enabled': emergencySmsEnabled,
    };
  }
}