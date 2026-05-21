import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'doctor_controller.dart';
import 'widgets/doctor_card.dart';
import 'package:mediq_app/presentation/widgets/global_error_widget.dart';
import '../../../shared/presentation/widgets/skeleton_loader.dart';

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
            child: RefreshIndicator(
              onRefresh: () async => ref.invalidate(doctorListProvider),
              child: doctorsAsync.when(
                loading: () => ListView.builder(
                  physics: const AlwaysScrollableScrollPhysics(),
                  padding: const EdgeInsets.all(16),
                  itemCount: 5,
                  itemBuilder: (context, index) => Padding(
                    padding: const EdgeInsets.only(bottom: 16),
                    child: SkeletonLoader(child: Container(height: 120, width: double.infinity, decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(16)))),
                  ),
                ),
                error: (err, stack) => ListView(
                  physics: const AlwaysScrollableScrollPhysics(),
                  children: [
                    SizedBox(
                      height: MediaQuery.of(context).size.height * 0.7,
                      child: GlobalErrorWidget(
                        error: err,
                        onRetry: () => ref.invalidate(doctorListProvider),
                      ),
                    ),
                  ],
                ),
                data: (doctors) {
                  if (doctors.isEmpty) {
                    return ListView(
                      physics: const AlwaysScrollableScrollPhysics(),
                      children: [
                        SizedBox(
                          height: MediaQuery.of(context).size.height * 0.7,
                          child: Center(
                            child: Text(
                              "No doctors found.",
                              style: theme.textTheme.bodyMedium,
                            ),
                          ),
                        ),
                      ],
                    );
                  }
  
                  return ListView.builder(
                    physics: const AlwaysScrollableScrollPhysics(),
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
          ),
        ],
      ),
    );
  }
}
