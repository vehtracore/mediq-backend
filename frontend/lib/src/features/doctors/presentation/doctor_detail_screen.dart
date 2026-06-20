import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:go_router/go_router.dart';
import '../../doctors/data/doctor_model.dart';

class DoctorDetailScreen extends StatelessWidget {
  final Doctor doctor;
  const DoctorDetailScreen({super.key, required this.doctor});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Scaffold(
      backgroundColor: theme.scaffoldBackgroundColor, // ✅ Dynamic
      body: CustomScrollView(slivers: [
        SliverAppBar(
            expandedHeight: 300,
            pinned: true,
            backgroundColor: theme.appBarTheme.backgroundColor,
            foregroundColor: theme.appBarTheme.foregroundColor,
            flexibleSpace: FlexibleSpaceBar(
                background: Center(
              child: doctor.imageUrl.isNotEmpty &&
                      doctor.imageUrl.startsWith('http')
                  ? CircleAvatar(
                      radius: 80,
                      backgroundImage: NetworkImage(doctor.imageUrl),
                    )
                  : const CircleAvatar(
                      radius: 80,
                      child: Icon(Icons.person, size: 80),
                    ),
            ))),
        SliverToBoxAdapter(
            child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(doctor.fullName,
                                      style: GoogleFonts.poppins(
                                          fontSize: 24,
                                          fontWeight: FontWeight.bold,
                                          color: theme
                                              .textTheme.bodyLarge?.color)),
                                  Text(doctor.specialty,
                                      style: GoogleFonts.lato(
                                          fontSize: 16,
                                          color: Colors.grey[600])),
                                  if (doctor.licenseNumber != null &&
                                      doctor.licenseNumber!.isNotEmpty) ...[
                                    const SizedBox(height: 8),
                                    Container(
                                      padding: const EdgeInsets.symmetric(
                                          horizontal: 8, vertical: 4),
                                      decoration: BoxDecoration(
                                        color:
                                            Colors.blue.withValues(alpha: 0.1),
                                        borderRadius: BorderRadius.circular(6),
                                        border: Border.all(
                                            color: Colors.blue
                                                .withValues(alpha: 0.3)),
                                      ),
                                      child: Row(
                                        mainAxisSize: MainAxisSize.min,
                                        children: [
                                          const Icon(Icons.verified,
                                              size: 14, color: Colors.blue),
                                          const SizedBox(width: 4),
                                          Text(
                                            "MDCN: ${doctor.licenseNumber}",
                                            style: const TextStyle(
                                                fontSize: 12,
                                                fontWeight: FontWeight.bold,
                                                color: Colors.blue),
                                          ),
                                        ],
                                      ),
                                    ),
                                  ],
                                ]),
                            Chip(
                                label: Text("${doctor.rating} ★"),
                                backgroundColor:
                                    Colors.amber.withValues(alpha: 0.2))
                          ]),
                      const SizedBox(height: 24),
                      Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            _buildStat("Patients", "${doctor.reviewCount}+",
                                Icons.people, theme),
                            _buildStat(
                                "Experience",
                                "${doctor.yearsExperience} Yrs",
                                Icons.work,
                                theme),
                            _buildStat("Rating", "${doctor.rating}", Icons.star,
                                theme),
                          ]),
                      const SizedBox(height: 24),
                      Text("About",
                          style: GoogleFonts.poppins(
                              fontSize: 18,
                              fontWeight: FontWeight.bold,
                              color: theme.textTheme.bodyLarge?.color)),
                      Text(doctor.bio ?? "No bio.",
                          style: GoogleFonts.lato(
                              height: 1.5,
                              color: theme.textTheme.bodyMedium?.color)),
                    ]))),
      ]),
      bottomNavigationBar: SafeArea(
          child: Padding(
              padding: const EdgeInsets.all(16),
              child: ElevatedButton(
                onPressed: doctor.isAvailable
                    ? () => context.push('/book_appointment', extra: doctor)
                    : null,
                style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF4A90E2),
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.all(16)),
                child: Text(
                    "Book ${doctor.consultationDurationMinutes} min · ₦${doctor.consultationFee.toInt()}",
                    style: const TextStyle(fontSize: 18)),
              ))),
    );
  }

  Widget _buildStat(String label, String val, IconData icon, ThemeData theme) {
    return Column(children: [
      Icon(icon, color: const Color(0xFF4A90E2)),
      const SizedBox(height: 4),
      Text(val,
          style: TextStyle(
              fontWeight: FontWeight.bold,
              color: theme.textTheme.bodyLarge?.color)),
      Text(label, style: const TextStyle(fontSize: 12, color: Colors.grey))
    ]);
  }
}
