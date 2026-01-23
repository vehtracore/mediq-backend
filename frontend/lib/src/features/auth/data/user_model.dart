// ... inside user_model.dart ...

  factory User.fromJson(Map<String, dynamic> json) {
    // 1. Get raw path
    String rawImage = json['image_url'] ?? json['profile_image'] ?? '';
    
    // 2. Fix URL for Render
    String finalUrl = '';
    if (rawImage.isNotEmpty) {
      if (rawImage.startsWith('http')) {
        finalUrl = rawImage;
      } else {
        // ⚠️ REPLACE THIS WITH YOUR REAL RENDER URL ⚠️
        const baseUrl = "https://mediq-backend.onrender.com"; 
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
      subscriptionTier: json['subscription_tier'] ?? 'free',
      imageUrl: finalUrl, // ✅ Sanitized
      location: json['location'],
      // ... map rest of fields ...
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
// ...