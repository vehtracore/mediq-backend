import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'package:mediq_app/src/features/auth/presentation/auth_controller.dart';
import 'package:mediq_app/src/features/auth/data/auth_repository.dart';
import 'package:mediq_app/src/features/content/data/content_repository.dart';
import 'package:mediq_app/src/features/admin/presentation/content/admin_content_editor.dart';
import 'package:mediq_app/src/features/auth/data/user_model.dart';
import 'package:mediq_app/src/shared/presentation/widgets/skeleton_loader.dart';
import 'package:mediq_app/presentation/widgets/global_error_widget.dart';

final adminStatsProvider = FutureProvider.autoDispose((ref) async {
  final dio = ref.watch(dioProvider);
  final response = await dio.get('/api/v1/admin/stats');
  return response.data;
});

final unverifiedDoctorsProvider = FutureProvider.autoDispose((ref) async {
  final dio = ref.watch(dioProvider);
  final response = await dio.get('/api/v1/admin/doctors/pending');
  return response.data;
});

/// Purpose: Drives the user management table in the Admin Dashboard, allowing administrators
/// to view, suspend, and reactivate accounts across the platform.
///
/// Data Source: Directly uses `dioProvider` to hit the `/api/v1/admin/users` endpoint.
///
/// Invalidation Strategy: Should be explicitly invalidated via `ref.invalidate(allUsersProvider)` 
/// on pull-to-refresh of the users tab, or immediately after a successful suspend/reactivate mutation.
///
/// Error & Loading Annotations: Network exceptions (e.g., `DioException`) are caught by Riverpod 
/// and translated into localized strings by the `GlobalErrorWidget` wrapped around this provider's `error` state.
final allUsersProvider = FutureProvider.autoDispose<List<User>>((ref) async {
  final dio = ref.watch(dioProvider);
  final response = await dio.get('/api/v1/admin/users');
  final List data = response.data;
  return data.map((json) => User.fromJson(json)).toList();
});

final adminContentProvider = FutureProvider.autoDispose((ref) async {
  return await ref.watch(contentRepositoryProvider).getHealthTips();
});

class AdminDashboard extends ConsumerStatefulWidget {
  const AdminDashboard({super.key});
  @override
  ConsumerState<AdminDashboard> createState() => _AdminDashboardState();
}

class _AdminDashboardState extends ConsumerState<AdminDashboard> {
  final TextEditingController _searchCtrl = TextEditingController();
  String _searchQuery = "";

  @override
  void dispose() {
    _searchCtrl.dispose();
    super.dispose();
  }

  Future<void> _verifyDoctor(int id) async {
    try {
      await ref.read(dioProvider).put('/api/v1/admin/doctors/$id/verify');
      // ✅ FIX: Use invalidate() — consistent with _rejectDoctor
      ref.invalidate(unverifiedDoctorsProvider);
      ref.invalidate(adminStatsProvider);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text("Doctor Verified"), backgroundColor: Colors.green));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text("$e")));
      }
    }
  }

  Future<void> _rejectDoctor(int id, String reason) async {
    try {
      await ref.read(dioProvider).post(
        '/api/v1/admin/doctors/$id/reject',
        data: {'rejection_reason': reason},
      );
      // ✅ FIX: Use invalidate() — the correct method for autoDispose providers.
      // ref.refresh() on an autoDispose provider can silently no-op if the
      // provider was already disposed. invalidate() guarantees a cache bust
      // and forces a fresh network fetch on the next ref.watch() cycle.
      ref.invalidate(unverifiedDoctorsProvider);
      ref.invalidate(adminStatsProvider); // Keep the Overview counter in sync
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text("Application Rejected"),
            backgroundColor: Colors.orange));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text("Reject failed: $e"), backgroundColor: Colors.red));
      }
    }
  }

  Future<void> _suspendUser(String id) async {
    try {
      await ref.read(dioProvider).put('/api/v1/admin/users/$id/suspend');
      ref.refresh(allUsersProvider);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text("User Status Updated"),
            backgroundColor: Colors.blue));
      }
    } catch (e) {}
  }

  void _showLicenseDialog(String url) {
    showDialog(
      context: context,
      builder: (ctx) => Dialog(
        backgroundColor: Theme.of(context).dialogBackgroundColor,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            AppBar(
              title: const Text("Medical License"),
              leading: IconButton(
                  icon: const Icon(Icons.close),
                  onPressed: () => Navigator.pop(ctx)),
              elevation: 0,
              backgroundColor: Colors.transparent,
              foregroundColor: Theme.of(context).iconTheme.color,
            ),
            InteractiveViewer(
              child: Image.network(
                url,
                loadingBuilder: (ctx, child, loadingProgress) {
                  if (loadingProgress == null) return child;
                  return const SizedBox(
                      height: 200,
                      child: Center(child: CircularProgressIndicator()));
                },
                errorBuilder: (context, error, stackTrace) => const Padding(
                  padding: EdgeInsets.all(20.0),
                  child: Column(children: [
                    Icon(Icons.broken_image, size: 50, color: Colors.grey),
                    Text("Could not load image")
                  ]),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;

    return DefaultTabController(
      length: 4,
      child: Scaffold(
        backgroundColor: theme.scaffoldBackgroundColor, // ✅ Dynamic Background
        appBar: AppBar(
          title: const Text("Admin Console",
              style: TextStyle(fontWeight: FontWeight.bold)),
          backgroundColor: isDark
              ? const Color(0xFF1E1E1E)
              : Colors.blueGrey[900], // ✅ Darker header in dark mode
          foregroundColor: Colors.white,
          bottom: const TabBar(
            isScrollable: true,
            indicatorColor: Colors.orange,
            labelColor: Colors.white,
            unselectedLabelColor: Colors.white70,
            tabs: [
              Tab(icon: Icon(Icons.dashboard), text: "Overview"),
              Tab(icon: Icon(Icons.verified_user), text: "Verifications"),
              Tab(icon: Icon(Icons.people), text: "Users"),
              Tab(icon: Icon(Icons.article), text: "Content"),
            ],
          ),
          actions: [
            IconButton(
              icon: const Icon(Icons.logout, color: Colors.redAccent),
              onPressed: () async {
                await ref.read(authControllerProvider.notifier).logout();
                if (context.mounted) context.go('/auth');
              },
            ),
          ],
        ),
        body: TabBarView(
          children: [
            _buildOverviewTab(),
            _buildDoctorsTab(),
            _buildUsersTab(),
            _buildContentTab(),
          ],
        ),
        floatingActionButton: FloatingActionButton(
          backgroundColor: Colors.orange,
          child: const Icon(Icons.add),
          onPressed: () async {
            final result = await Navigator.push(
                context,
                MaterialPageRoute(
                    builder: (_) => const AdminContentEditorScreen()));
            if (result == true) ref.refresh(adminContentProvider);
          },
        ),
      ),
    );
  }

  Widget _buildOverviewTab() {
    final statsAsync = ref.watch(adminStatsProvider);
    return RefreshIndicator(
      onRefresh: () async => ref.invalidate(adminStatsProvider),
      child: statsAsync.when(
        loading: () => ListView.builder(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(16),
          itemCount: 4,
          itemBuilder: (context, index) => Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: SkeletonLoader(child: Container(height: 100, width: double.infinity, decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(12)))),
          ),
        ),
        error: (e, _) => ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          children: [
            SizedBox(
              height: MediaQuery.of(context).size.height * 0.7,
              child: GlobalErrorWidget(
                error: e,
                onRetry: () => ref.invalidate(adminStatsProvider),
              ),
            ),
          ],
        ),
        data: (stats) => SingleChildScrollView(
          physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text("System Health",
                style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
            const SizedBox(height: 16),
            Wrap(
              spacing: 16,
              runSpacing: 16,
              children: [
                _StatCard(
                    title: "Total Revenue",
                    value: "₦${stats['total_revenue']}",
                    color: Colors.green,
                    icon: Icons.payments),
                _StatCard(
                    title: "Subscribed",
                    value: "${stats['subscribed_users'] ?? 0}",
                    color: Colors.amber,
                    icon: Icons.star_border),
                _StatCard(
                    title: "Pending Docs",
                    value: "${stats['pending_verifications']}",
                    color: Colors.orange,
                    icon: Icons.warning_amber),
                _StatCard(
                    title: "Total Users",
                    value: "${stats['total_users']}",
                    color: Colors.blue,
                    icon: Icons.person),
                _StatCard(
                    title: "Total Doctors",
                    value: "${stats['total_doctors']}",
                    color: Colors.teal,
                    icon: Icons.medical_services),
                _StatCard(
                    title: "Active Appts",
                    value: "${stats['active_appointments']}",
                    color: Colors.purple,
                    icon: Icons.calendar_today),
              ],
            ),
          ],
        ),
      ),
      ),
    );
  }

  Widget _buildDoctorsTab() {
    final docsAsync = ref.watch(unverifiedDoctorsProvider);
    return RefreshIndicator(
      onRefresh: () async => ref.invalidate(unverifiedDoctorsProvider),
      child: docsAsync.when(
        loading: () => ListView.builder(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(16),
          itemCount: 4,
          itemBuilder: (context, index) => Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: SkeletonLoader(child: Container(height: 100, width: double.infinity, decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(12)))),
          ),
        ),
        error: (e, _) => ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          children: [
            SizedBox(
              height: MediaQuery.of(context).size.height * 0.7,
              child: GlobalErrorWidget(
                error: e,
                onRetry: () => ref.invalidate(unverifiedDoctorsProvider),
              ),
            ),
          ],
        ),
        data: (doctors) => doctors.isEmpty
            ? ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                children: [
                  SizedBox(
                    height: MediaQuery.of(context).size.height * 0.7,
                    child: const Center(child: Text("No pending verifications.")),
                  ),
                ],
              )
            : ListView.builder(
                physics: const AlwaysScrollableScrollPhysics(),
                padding: const EdgeInsets.all(16),
              itemCount: doctors.length,
              itemBuilder: (ctx, i) {
                final licenseData = doctors[i]['license_number'] ?? "";
                final bool isUrl = licenseData.toString().startsWith("http");
                final theme = Theme.of(ctx);

                return Card(
                  color: theme.cardTheme.color, // ✅ Dynamic Card
                  child: Column(
                    children: [
                      ListTile(
                        leading: const CircleAvatar(
                            child: Icon(Icons.local_hospital)),
                        title: Text(doctors[i]['full_name'],
                            style: theme.textTheme.bodyLarge),
                        subtitle: Text(doctors[i]['specialty'] ?? "Specialist",
                            style: theme.textTheme.bodyMedium),
                      ),
                      Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 16.0),
                        child: Row(
                          children: [
                            if (isUrl)
                              TextButton.icon(
                                onPressed: () =>
                                    _showLicenseDialog(licenseData),
                                icon: const Icon(Icons.image, size: 18),
                                label: const Text("View License"),
                              )
                            else
                              Text("License: $licenseData",
                                  style: const TextStyle(color: Colors.grey)),
                            const Spacer(),
                            IconButton.filledTonal(
                                icon: const Icon(Icons.close),
                                tooltip: "Reject",
                                style: IconButton.styleFrom(
                                    backgroundColor: theme.colorScheme.primary.withOpacity(0.15),
                                    foregroundColor: theme.colorScheme.primary,
                                    elevation: 0,
                                ),
                                onPressed: () {
                                  final reasonCtrl = TextEditingController();
                                  showDialog(
                                    context: ctx,
                                    builder: (context) => AlertDialog(
                                      title: const Text("Reject Application"),
                                      content: TextField(
                                        controller: reasonCtrl,
                                        decoration: const InputDecoration(
                                          hintText: "Enter rejection reason",
                                        ),
                                      ),
                                      actions: [
                                        TextButton(
                                          onPressed: () => Navigator.pop(context),
                                          child: const Text("Cancel"),
                                        ),
                                        ElevatedButton(
                                          onPressed: () {
                                            final reason = reasonCtrl.text.trim();
                                            if (reason.isNotEmpty) {
                                              Navigator.pop(context);
                                              _rejectDoctor(doctors[i]['id'], reason);
                                            }
                                          },
                                          style: ElevatedButton.styleFrom(backgroundColor: Colors.red, foregroundColor: Colors.white),
                                          child: const Text("Confirm Reject"),
                                        ),
                                      ],
                                    ),
                                  );
                                }),
                            const SizedBox(width: 8),
                            IconButton.filledTonal(
                                icon: const Icon(Icons.check),
                                tooltip: "Verify",
                                style: IconButton.styleFrom(
                                    backgroundColor: theme.colorScheme.primary.withOpacity(0.15),
                                    foregroundColor: theme.colorScheme.primary,
                                    elevation: 0,
                                ),
                                onPressed: () =>
                                    _verifyDoctor(doctors[i]['id'])),
                          ],
                        ),
                      ),
                      const SizedBox(height: 8),
                    ],
                  ),
                );
              },
            ),
      ),
    );
  }

  Widget _buildUsersTab() {
    final usersAsync = ref.watch(allUsersProvider);
    final theme = Theme.of(context);

    return Column(
      children: [
        Container(
          padding: const EdgeInsets.all(16),
          color: theme.cardTheme.color, // ✅ Dynamic Search Bar Background
          child: TextField(
            controller: _searchCtrl,
            style: theme.textTheme.bodyLarge, // ✅ Text color
            decoration: InputDecoration(
              hintText: "Search...",
              hintStyle: TextStyle(color: Colors.grey[400]),
              prefixIcon: const Icon(Icons.search),
              filled: true,
              fillColor: theme.inputDecorationTheme.fillColor,
              border:
                  OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
            ),
            onChanged: (val) =>
                setState(() => _searchQuery = val.toLowerCase()),
          ),
        ),
        Expanded(
          child: RefreshIndicator(
            onRefresh: () async => ref.invalidate(allUsersProvider),
            child: usersAsync.when(
              loading: () => ListView.builder(
                physics: const AlwaysScrollableScrollPhysics(),
                padding: const EdgeInsets.all(16),
                itemCount: 6,
                itemBuilder: (context, index) => Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: SkeletonLoader(child: Container(height: 70, width: double.infinity, decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(12)))),
                ),
              ),
              error: (e, _) => ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                children: [
                  SizedBox(
                    height: MediaQuery.of(context).size.height * 0.7,
                    child: GlobalErrorWidget(
                      error: e,
                      onRetry: () => ref.invalidate(allUsersProvider),
                    ),
                  ),
                ],
              ),
              data: (users) {
                final filtered = users.where((u) {
                  final fullName = "${u.firstName} ${u.lastName}";
                  return fullName.toLowerCase().contains(_searchQuery) ||
                      u.email.toLowerCase().contains(_searchQuery);
                }).toList();
  
                if (filtered.isEmpty) {
                  return ListView(
                    physics: const AlwaysScrollableScrollPhysics(),
                    children: [
                      SizedBox(
                        height: MediaQuery.of(context).size.height * 0.7,
                        child: const Center(child: Text("No users found.")),
                      ),
                    ],
                  );
                }
  
                return ListView.builder(
                  physics: const AlwaysScrollableScrollPhysics(),
                  itemCount: filtered.length,
                  padding: const EdgeInsets.all(16),
                itemBuilder: (ctx, i) {
                  final user = filtered[i];
                  final fullName = "${user.firstName} ${user.lastName}";
                  final isBanned = user.isBanned; // ✅ Dynamic status

                  if (user.role == 'admin') {
                    return ListTile(
                        title: Text(fullName), subtitle: const Text("ADMIN"));
                  }

                  // ✅ Dynamic Card Logic for Banned/Normal users
                  final cardColor = isBanned
                      ? (theme.brightness == Brightness.dark
                          ? Colors.red.withOpacity(0.2)
                          : Colors.red[50])
                      : theme.cardTheme.color;

                  return Card(
                    color: cardColor,
                    child: ListTile(
                      leading: CircleAvatar(
                        backgroundColor:
                            user.role == 'doctor' ? Colors.blue : Colors.green,
                        child: const Icon(Icons.person, color: Colors.white),
                      ),
                      title: Text(fullName, style: theme.textTheme.bodyLarge),
                      subtitle: Text(
                          "${user.email} • ${user.role.toUpperCase()}",
                          style: theme.textTheme.bodyMedium),
                      trailing: IconButton.filledTonal(
                        onPressed: () => _suspendUser(user.id),
                        icon: Icon(isBanned ? Icons.check_circle_outline : Icons.block),
                        tooltip: isBanned ? "Reactivate" : "Suspend",
                        style: IconButton.styleFrom(
                            backgroundColor: theme.colorScheme.primary.withOpacity(0.15),
                            foregroundColor: theme.colorScheme.primary,
                            elevation: 0,
                        ),
                      ),
                    ),
                  );
                },
              );
            },
          ),
        ),
      ),
      ],
    );
  }

  Widget _buildContentTab() {
    final contentAsync = ref.watch(adminContentProvider);
    final theme = Theme.of(context);

    return RefreshIndicator(
      onRefresh: () async => ref.invalidate(adminContentProvider),
      child: contentAsync.when(
        loading: () => ListView.builder(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(16),
          itemCount: 5,
          itemBuilder: (context, index) => Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: SkeletonLoader(child: Container(height: 80, width: double.infinity, decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(12)))),
          ),
        ),
        error: (e, _) => ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          children: [
            SizedBox(
              height: MediaQuery.of(context).size.height * 0.7,
              child: GlobalErrorWidget(
                error: e,
                onRetry: () => ref.invalidate(adminContentProvider),
              ),
            ),
          ],
        ),
        data: (tips) => ListView.builder(
          physics: const AlwaysScrollableScrollPhysics(),
          itemCount: tips.length,
          padding: const EdgeInsets.all(16),
        itemBuilder: (ctx, i) => Card(
          color: theme.cardTheme.color, // ✅ Dynamic Card
          margin: const EdgeInsets.only(bottom: 12),
          child: ListTile(
            title: Text(tips[i].title, style: theme.textTheme.bodyLarge),
            trailing: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                IconButton.filledTonal(
                  icon: const Icon(Icons.edit, size: 20),
                  tooltip: "Edit",
                  style: IconButton.styleFrom(
                      backgroundColor: theme.colorScheme.primary.withOpacity(0.15),
                      foregroundColor: theme.colorScheme.primary,
                      elevation: 0,
                  ),
                  onPressed: () async {
                    final result = await Navigator.push(
                        context,
                        MaterialPageRoute(
                            builder: (_) =>
                                AdminContentEditorScreen(healthTip: tips[i])));
                    if (result == true) ref.refresh(adminContentProvider);
                  },
                ),
                const SizedBox(width: 8),
                IconButton.filledTonal(
                  icon: const Icon(Icons.delete, size: 20),
                  tooltip: "Delete",
                  style: IconButton.styleFrom(
                      backgroundColor: theme.colorScheme.primary.withOpacity(0.15),
                      foregroundColor: theme.colorScheme.primary,
                      elevation: 0,
                  ),
                  onPressed: () async {
                    await ref
                        .read(contentRepositoryProvider)
                        .deleteHealthTip(tips[i].id);
                    ref.refresh(adminContentProvider);
                  },
                ),
              ],
            ),
          ),
        ),
      ),
      ),
    );
  }
}

class _StatCard extends StatelessWidget {
  final String title, value;
  final Color color;
  final IconData icon;
  const _StatCard(
      {required this.title,
      required this.value,
      required this.color,
      required this.icon});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final width = (MediaQuery.of(context).size.width - 48) / 2;

    return Container(
      width: width,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: theme.cardTheme.color, // ✅ Dynamic Card Background
        borderRadius: BorderRadius.circular(12),
        border: Border(left: BorderSide(color: color, width: 4)),
        boxShadow: theme.brightness == Brightness.dark
            ? []
            : [BoxShadow(color: Colors.grey.withOpacity(0.1), blurRadius: 5)],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: color, size: 32),
          const SizedBox(height: 12),
          Text(value,
              style: theme.textTheme.titleLarge?.copyWith(fontSize: 20)),
          Text(title, style: TextStyle(fontSize: 12, color: Colors.grey[600])),
        ],
      ),
    );
  }
}
