
class Doctor {
  final int id;
  final String fullName;
  final String specialty;
  final String imageUrl;
  final double hourlyRate;
  final double rating;
  final int reviewCount;
  final bool isAvailable;
  final String? bio;
  final bool isVerified;
  final int yearsExperience;
  final String? licenseNumber;
  final String status;          // 'pending' | 'active' | 'rejected'
  final String? rejectionReason;

  Doctor({
    required this.id, required this.fullName, required this.specialty, required this.imageUrl,
    required this.hourlyRate, required this.rating, required this.reviewCount, required this.isAvailable,
    this.bio, required this.isVerified, required this.yearsExperience, this.licenseNumber,
    this.status = 'pending', this.rejectionReason,
  });

  factory Doctor.fromJson(Map<String, dynamic> json) {
    return Doctor(
      id: json['id'],
      fullName: json['full_name'],
      specialty: json['specialty'],
      imageUrl: json['image_url'] ?? 'https://i.pravatar.cc/150',
      hourlyRate: (json['hourly_rate'] as num).toDouble(),
      rating: (json['rating'] as num).toDouble(),
      reviewCount: json['review_count'],
      isAvailable: json['is_available'] ?? false,
      bio: json['bio'],
      isVerified: json['is_verified'] ?? false,
      yearsExperience: json['years_experience'] ?? 0,
      licenseNumber: json['license_number'],
      status: json['status'] ?? 'pending',
      rejectionReason: json['rejection_reason'],
    );
  }
}
