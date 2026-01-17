import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'doctor_controller.dart';
import 'widgets/doctor_card.dart';

class DoctorSearchScreen extends ConsumerStatefulWidget {
  const DoctorSearchScreen({super.key});

  @override
  ConsumerState<DoctorSearchScreen> createState() => _DoctorSearchScreenState();
}

class _DoctorSearchScreenState extends ConsumerState<DoctorSearchScreen> {
  final TextEditingController _searchController = TextEditingController();

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final doctorsAsync = ref.watch(doctorListProvider);
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;

    return Scaffold(
      backgroundColor: theme.scaffoldBackgroundColor, // ✅ Dynamic Background
      appBar: AppBar(
        title: Text(
          "Find a Specialist",
          style: theme.textTheme.titleLarge?.copyWith(
            fontWeight: FontWeight.bold,
          ), // ✅ Dynamic Text
        ),
        backgroundColor: theme.appBarTheme.backgroundColor, // ✅ Dynamic
        elevation: 0,
        iconTheme: theme.iconTheme, // ✅ Dynamic Icons
      ),
      body: Column(
        children: [
          // --- Search Bar ---
          Container(
            color: theme.appBarTheme.backgroundColor, // ✅ matches header
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
            child: TextField(
              controller: _searchController,
              style: theme.textTheme.bodyLarge, // ✅ Dynamic Input Text
              decoration: InputDecoration(
                hintText: "Search doctors, specialties...",
                hintStyle: TextStyle(
                  color: isDark ? Colors.grey[400] : Colors.grey[600],
                ),
                prefixIcon: const Icon(Icons.search, color: Colors.grey),
                filled: true,
                fillColor:
                    theme.inputDecorationTheme.fillColor, // ✅ Dynamic Fill
                contentPadding: const EdgeInsets.symmetric(
                  vertical: 0,
                  horizontal: 20,
                ),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(16),
                  borderSide: BorderSide.none,
                ),
              ),
            ),
          ),

          // --- List of Doctors ---
          Expanded(
            child: doctorsAsync.when(
              loading: () => const Center(
                child: CircularProgressIndicator(color: Color(0xFF4A90E2)),
              ),
              error: (err, stack) => Center(
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    const Icon(
                      Icons.error_outline,
                      size: 48,
                      color: Colors.red,
                    ),
                    const SizedBox(height: 16),
                    Text(
                      "Failed to load doctors.\n${err.toString()}",
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        color: theme.textTheme.bodyMedium?.color,
                      ),
                    ),
                  ],
                ),
              ),
              data: (doctors) {
                if (doctors.isEmpty) {
                  return Center(
                    child: Text(
                      "No doctors found.",
                      style: theme.textTheme.bodyMedium,
                    ),
                  );
                }

                return ListView.builder(
                  padding: const EdgeInsets.all(16),
                  itemCount: doctors.length,
                  itemBuilder: (context, index) {
                    final doctor = doctors[index];
                    return DoctorCard(
                      doctor: doctor,
                      onTap: () {
                        context.push('/doctor_detail', extra: doctor);
                      },
                    );
                  },
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}
