class User {
  final String id;
  final String email;
  final String firstName;
  final String lastName;
  final String role;
  final String subscriptionTier;
  final String imageUrl; // ✅ Added
  final String? location; // ✅ Added

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
    return User(
      id: json['id'].toString(),
      email: json['email'] ?? '',
      firstName: json['first_name'] ?? '',
      lastName: json['last_name'] ?? '',
      role: json['role'] ?? 'patient',
      subscriptionTier: json['subscription_tier'] ?? 'free',
      // Check both keys to be safe
      imageUrl: json['image_url'] ?? json['profile_image'] ?? '', 
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