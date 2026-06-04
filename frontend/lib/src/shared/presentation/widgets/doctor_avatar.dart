import 'package:flutter/material.dart';

class DoctorAvatar extends StatelessWidget {
  final String imageUrl;
  final String fullName;
  final double radius;

  const DoctorAvatar({
    super.key,
    required this.imageUrl,
    required this.fullName,
    this.radius = 40,
  });

  String _getInitials(String name) {
    if (name.isEmpty) return 'DR';
    final parts = name.trim().split(' ').where((p) => p.isNotEmpty).toList();
    if (parts.isEmpty) return 'DR';
    
    // Attempt to skip "Dr." prefix
    int startIndex = 0;
    if (parts.length > 1 && parts[0].toLowerCase().replaceAll('.', '') == 'dr') {
      startIndex = 1;
    }

    if (parts.length - startIndex == 1) {
      return parts[startIndex][0].toUpperCase();
    } else if (parts.length - startIndex >= 2) {
      return '${parts[startIndex][0].toUpperCase()}${parts[startIndex + 1][0].toUpperCase()}';
    }
    
    return 'DR';
  }

  @override
  Widget build(BuildContext context) {
    final hasValidUrl = imageUrl.isNotEmpty && imageUrl.startsWith('http');
    final backgroundColor = Theme.of(context).colorScheme.surfaceContainerHighest;
    final primaryColor = Theme.of(context).colorScheme.primary;

    if (hasValidUrl) {
      return CircleAvatar(
        radius: radius,
        backgroundColor: backgroundColor,
        backgroundImage: NetworkImage(imageUrl),
        onBackgroundImageError: (_, __) {},
        child: null,
      );
    }

    return CircleAvatar(
      radius: radius,
      backgroundColor: backgroundColor,
      child: Icon(Icons.person, color: primaryColor, size: radius * 1.2),
    );
  }
}
