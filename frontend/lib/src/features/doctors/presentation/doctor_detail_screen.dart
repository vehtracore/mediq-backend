
import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:go_router/go_router.dart';
import '../../doctors/data/doctor_model.dart';

class DoctorDetailScreen extends StatelessWidget {
  final Doctor doctor;
  const DoctorDetailScreen({super.key, required this.doctor});

  @override
  Widget build(BuildContext context) {
    final statusColor = doctor.isAvailable ? Colors.green : Colors.grey;
    return Scaffold(
      body: CustomScrollView(slivers: [
        SliverAppBar(expandedHeight: 300, pinned: true, flexibleSpace: FlexibleSpaceBar(background: Image.network(doctor.imageUrl, fit: BoxFit.cover))),
        SliverToBoxAdapter(child: Padding(padding: const EdgeInsets.all(24), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
           Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
             Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
               Text(doctor.fullName, style: GoogleFonts.poppins(fontSize: 24, fontWeight: FontWeight.bold)),
               Text(doctor.specialty, style: GoogleFonts.lato(fontSize: 16, color: Colors.grey[600])),
             ]),
             Chip(label: Text("${doctor.rating} ★"), backgroundColor: Colors.amber.withOpacity(0.2))
           ]),
           const SizedBox(height: 24),
           Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
             _buildStat("Patients", "${doctor.reviewCount}+", Icons.people),
             _buildStat("Experience", "${doctor.yearsExperience} Yrs", Icons.work), // <--- REAL DATA
             _buildStat("Rating", "${doctor.rating}", Icons.star),
           ]),
           const SizedBox(height: 24),
           Text("About", style: GoogleFonts.poppins(fontSize: 18, fontWeight: FontWeight.bold)),
           Text(doctor.bio ?? "No bio.", style: GoogleFonts.lato(height: 1.5)),
        ]))),
      ]),
      bottomNavigationBar: SafeArea(child: Padding(padding: const EdgeInsets.all(16), child: ElevatedButton(
        onPressed: doctor.isAvailable ? () => context.push('/book_appointment', extra: doctor) : null,
        style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF4A90E2), foregroundColor: Colors.white, padding: const EdgeInsets.all(16)),
        child: Text("Book for ₦${doctor.hourlyRate.toInt()}", style: const TextStyle(fontSize: 18)),
      ))),
    );
  }

  Widget _buildStat(String label, String val, IconData icon) {
    return Column(children: [Icon(icon, color: const Color(0xFF4A90E2)), const SizedBox(height: 4), Text(val, style: const TextStyle(fontWeight: FontWeight.bold)), Text(label, style: const TextStyle(fontSize: 12, color: Colors.grey))]);
  }
}
