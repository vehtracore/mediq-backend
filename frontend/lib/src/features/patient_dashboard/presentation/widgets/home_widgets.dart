
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';
import 'package:mediq_app/src/features/appointments/data/appointment_repository.dart';
import 'package:mediq_app/src/features/auth/presentation/user_controller.dart';
import 'package:mediq_app/src/features/appointments/data/appointment_model.dart';

final nextAppointmentProvider = FutureProvider.autoDispose<Appointment?>((ref) async {
  final appointments = await ref.watch(appointmentRepositoryProvider).getMyAppointments();
  final upcoming = appointments.where((a) => a.status == 'confirmed' && a.startTime.isAfter(DateTime.now())).toList();
  if (upcoming.isEmpty) return null;
  upcoming.sort((a, b) => a.startTime.compareTo(b.startTime));
  return upcoming.first;
});

class HomeHeader extends StatelessWidget {
  final String userName;
  const HomeHeader({super.key, required this.userName});
  @override
  Widget build(BuildContext context) {
    return Container(
      // --- GRADIENT FADE FIX ---
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topCenter, end: Alignment.bottomCenter,
          colors: [Colors.white.withOpacity(0.8), const Color(0xFFF9FAFB)],
          stops: const [0.0, 1.0],
        ),
      ),
      padding: const EdgeInsets.symmetric(vertical: 16),
      child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
        Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text("Welcome Back,", style: TextStyle(fontSize: 16, color: Colors.grey[600], fontWeight: FontWeight.w500)),
          const SizedBox(height: 4),
          Text(userName, style: const TextStyle(fontSize: 28, fontWeight: FontWeight.bold, color: Color(0xFF1A1A1A), letterSpacing: -0.5)),
        ]),
        GestureDetector(onTap: () => context.push('/notifications'), child: Container(padding: const EdgeInsets.all(12), decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(16), border: Border.all(color: Colors.grey.withOpacity(0.1)), boxShadow: [BoxShadow(color: const Color(0xFF4A90E2).withOpacity(0.1), blurRadius: 15, offset: const Offset(0, 5))]), child: const Icon(Icons.notifications_none_rounded, color: Color(0xFF4A90E2), size: 26))),
      ]),
    );
  }
}
// ... (Rest of AppointmentCard and QuickActionGrid remains the same as previous version)
class AppointmentCard extends ConsumerWidget {
  const AppointmentCard({super.key});
  @override Widget build(BuildContext context, WidgetRef ref) {
    final nextApptAsync = ref.watch(nextAppointmentProvider);
    return nextApptAsync.when(loading: () => const SizedBox(height: 140), error: (e, _) => const SizedBox(), data: (appointment) {
      if (appointment == null) return Container(width: double.infinity, padding: const EdgeInsets.all(24), decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(32), border: Border.all(color: Colors.grey.withOpacity(0.1))), child: Row(children: [Container(padding: const EdgeInsets.all(12), decoration: BoxDecoration(color: const Color(0xFF4A90E2).withOpacity(0.1), shape: BoxShape.circle), child: const Icon(Icons.calendar_today, color: Color(0xFF4A90E2))), const SizedBox(width: 16), Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [const Text("No upcoming visits", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)), const SizedBox(height: 4), Text("Book a doctor to get started.", style: TextStyle(fontSize: 12, color: Colors.grey[600]))])), TextButton(onPressed: () => context.push('/find_doctor'), child: const Text("Book", style: TextStyle(fontWeight: FontWeight.bold)))]));
      final dateStr = DateFormat('MMM dd, yyyy').format(appointment.startTime);
      final timeStr = DateFormat('jm').format(appointment.startTime);
      return Container(width: double.infinity, padding: const EdgeInsets.all(24), decoration: BoxDecoration(borderRadius: BorderRadius.circular(32), gradient: const LinearGradient(colors: [Color(0xFF4A90E2), Color(0xFF00CEC9)]), boxShadow: [BoxShadow(color: const Color(0xFF4A90E2).withOpacity(0.4), blurRadius: 25, offset: const Offset(0, 10))]), child: Column(children: [Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [Container(padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6), decoration: BoxDecoration(color: Colors.white.withOpacity(0.2), borderRadius: BorderRadius.circular(12)), child: Row(children: [const Icon(Icons.calendar_today_rounded, color: Colors.white, size: 14), const SizedBox(width: 6), Text("$dateStr • $timeStr", style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 12))])), const Icon(Icons.videocam, color: Colors.white70)]), const SizedBox(height: 20), Row(children: [Container(decoration: BoxDecoration(shape: BoxShape.circle, border: Border.all(color: Colors.white.withOpacity(0.5), width: 2)), child: const CircleAvatar(radius: 26, backgroundColor: Colors.white24, child: Icon(Icons.person, color: Colors.white, size: 28))), const SizedBox(width: 16), Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(appointment.doctorName, style: const TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.bold)), const SizedBox(height: 4), const Text("Video Consultation", style: TextStyle(color: Colors.white70, fontSize: 14))]))])]));
    });
  }
}
class QuickActionGrid extends ConsumerWidget {
  const QuickActionGrid({super.key});
  void _showBookingOptions(BuildContext context, WidgetRef ref) {
    final userAsync = ref.watch(userProvider);
    String priceText = "Loading...";
    double priceVal = 4000.0;
    userAsync.whenData((user) { if (user.plan == 'premium') { priceText = "NGN 2,500 (Premium)"; priceVal = 2500.0; } else { priceText = "NGN 4,000 (Standard)"; priceVal = 4000.0; } });
    showModalBottomSheet(context: context, backgroundColor: Colors.transparent, builder: (ctx) => Container(padding: const EdgeInsets.all(24), decoration: const BoxDecoration(color: Colors.white, borderRadius: BorderRadius.vertical(top: Radius.circular(24))), child: Column(mainAxisSize: MainAxisSize.min, children: [ListTile(title: const Text("See a GP Now", style: TextStyle(fontWeight: FontWeight.bold)), subtitle: Text(priceText), leading: const Icon(Icons.flash_on, color: Colors.orange), onTap: () async { Navigator.pop(ctx); try { final appt = await ref.read(appointmentRepositoryProvider).bookGeneralConsultation("I need a doctor now."); if (context.mounted) context.push('/payment', extra: {'appointment': appt, 'amount': priceVal}); } catch (e) { if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("Error: $e"), backgroundColor: Colors.red)); } }), const Divider(), ListTile(title: const Text("Book a Specialist"), leading: const Icon(Icons.calendar_month, color: Color(0xFF4A90E2)), onTap: () { Navigator.pop(ctx); context.push('/find_doctor'); })])));
  }
  @override Widget build(BuildContext context, WidgetRef ref) {
    final actions = [{'icon': Icons.chat_bubble_outline_rounded, 'label': 'Check Symptoms', 'color': 0xFF4A90E2}, {'icon': Icons.person_search_rounded, 'label': 'Find Doctor', 'color': 0xFF00CEC9}, {'icon': Icons.local_pharmacy_outlined, 'label': 'Pharmacy', 'color': 0xFFFF7675}, {'icon': Icons.phone_in_talk, 'label': 'Emergency', 'color': 0xFFFDCB6E}];
    return GridView.builder(shrinkWrap: true, physics: const NeverScrollableScrollPhysics(), gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(crossAxisCount: 2, childAspectRatio: 1.3, crossAxisSpacing: 16, mainAxisSpacing: 16), itemCount: actions.length, itemBuilder: (context, index) { final item = actions[index]; final color = Color(item['color'] as int); return InkWell(onTap: () { if (index == 0) context.push('/chat'); else if (index == 1) _showBookingOptions(context, ref); else if (index == 3) context.push('/emergency'); else ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("${item['label']} coming soon!"))); }, borderRadius: BorderRadius.circular(24), child: Container(padding: const EdgeInsets.all(12), decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(24), boxShadow: [BoxShadow(color: Colors.grey.withOpacity(0.05), blurRadius: 20, offset: const Offset(0, 5))]), child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [Container(padding: const EdgeInsets.all(10), decoration: BoxDecoration(color: color.withOpacity(0.1), shape: BoxShape.circle), child: Icon(item['icon'] as IconData, color: color, size: 22)), const SizedBox(height: 8), Text(item['label'] as String, textAlign: TextAlign.center, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 13, color: Color(0xFF2D3436))) ]))); });
  }
}
