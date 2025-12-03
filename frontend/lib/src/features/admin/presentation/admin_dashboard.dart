import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'package:mediq_app/src/features/auth/presentation/auth_controller.dart';
import 'package:mediq_app/src/features/auth/data/auth_repository.dart';
import 'package:mediq_app/src/features/content/data/content_repository.dart';
import 'package:mediq_app/src/features/admin/presentation/content/admin_content_editor.dart';

final adminStatsProvider = FutureProvider.autoDispose((ref) async {
  final dio = ref.watch(dioProvider);
  final response = await dio.get('/api/v1/admin/stats');
  return response.data;
});

// --- UPDATED PROVIDER ---
final unverifiedDoctorsProvider = FutureProvider.autoDispose((ref) async {
  final dio = ref.watch(dioProvider);
  // Call the specific ADMIN endpoint for pending docs
  final response = await dio.get('/api/v1/admin/doctors/pending');
  return response.data;
});

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
      if (mounted)
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text("Doctor Verified"),
            backgroundColor: Colors.green,
          ),
        );
      ref.refresh(unverifiedDoctorsProvider);
      ref.refresh(adminStatsProvider);
    } catch (e) {}
  }

  Future<void> _rejectDoctor(int id) async {
    try {
      await ref.read(dioProvider).delete('/api/v1/admin/doctors/$id/reject');
      if (mounted)
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text("Application Rejected"),
            backgroundColor: Colors.orange,
          ),
        );
      ref.refresh(unverifiedDoctorsProvider);
    } catch (e) {}
  }

  Future<void> _suspendUser(int id) async {
    try {
      await ref.read(dioProvider).put('/api/v1/admin/users/$id/suspend');
      ref.refresh(allUsersProvider);
      if (mounted)
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text("User Status Updated"),
            backgroundColor: Colors.blue,
          ),
        );
    } catch (e) {}
  }

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 4,
      child: Scaffold(
        backgroundColor: Colors.grey[100],
        appBar: AppBar(
          title: const Text(
            "Admin Console",
            style: TextStyle(fontWeight: FontWeight.bold),
          ),
          backgroundColor: Colors.blueGrey[900],
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
                builder: (_) => const AdminContentEditorScreen(),
              ),
            );
            if (result == true) ref.refresh(adminContentProvider);
          },
        ),
      ),
    );
  }

  Widget _buildOverviewTab() {
    final statsAsync = ref.watch(adminStatsProvider);
    return statsAsync.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => Center(child: Text("Error: $e")),
      data: (stats) => SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              "System Health",
              style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 16),
            Wrap(
              spacing: 16,
              runSpacing: 16,
              children: [
                _StatCard(
                  title: "Total Revenue",
                  value: "₦${stats['total_revenue']}",
                  color: Colors.green,
                  icon: Icons.payments,
                ),
                _StatCard(
                  title: "Pending Docs",
                  value: "${stats['pending_verifications']}",
                  color: Colors.orange,
                  icon: Icons.warning_amber,
                ),
                _StatCard(
                  title: "Total Users",
                  value: "${stats['total_users']}",
                  color: Colors.blue,
                  icon: Icons.person,
                ),
                _StatCard(
                  title: "Total Doctors",
                  value: "${stats['total_doctors']}",
                  color: Colors.teal,
                  icon: Icons.medical_services,
                ),
                _StatCard(
                  title: "Active Appts",
                  value: "${stats['active_appointments']}",
                  color: Colors.purple,
                  icon: Icons.calendar_today,
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildDoctorsTab() {
    final docsAsync = ref.watch(unverifiedDoctorsProvider);
    return docsAsync.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => Center(child: Text("Error: $e")),
      data: (doctors) => doctors.isEmpty
          ? const Center(child: Text("No pending verifications."))
          : ListView.builder(
              padding: const EdgeInsets.all(16),
              itemCount: doctors.length,
              itemBuilder: (ctx, i) => Card(
                child: ListTile(
                  leading: const CircleAvatar(
                    child: Icon(Icons.local_hospital),
                  ),
                  title: Text(doctors[i]['full_name']),
                  subtitle: Text(
                    "License: ${doctors[i]['license_number'] ?? 'N/A'}",
                  ),
                  trailing: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      IconButton(
                        icon: const Icon(Icons.close, color: Colors.red),
                        onPressed: () => _rejectDoctor(doctors[i]['id']),
                      ),
                      IconButton(
                        icon: const Icon(Icons.check, color: Colors.green),
                        onPressed: () => _verifyDoctor(doctors[i]['id']),
                      ),
                    ],
                  ),
                ),
              ),
            ),
    );
  }

  Widget _buildUsersTab() {
    final usersAsync = ref.watch(allUsersProvider);
    return Column(
      children: [
        Container(
          padding: const EdgeInsets.all(16),
          color: Colors.white,
          child: TextField(
            controller: _searchCtrl,
            decoration: InputDecoration(
              hintText: "Search...",
              prefixIcon: const Icon(Icons.search),
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(12),
              ),
            ),
            onChanged: (val) =>
                setState(() => _searchQuery = val.toLowerCase()),
          ),
        ),
        Expanded(
          child: usersAsync.when(
            loading: () => const Center(child: CircularProgressIndicator()),
            error: (e, _) => Center(child: Text("Error: $e")),
            data: (users) {
              final filtered = users
                  .where(
                    (u) =>
                        u.fullName.toLowerCase().contains(
                          _searchQuery.toLowerCase(),
                        ) ||
                        u.email.toLowerCase().contains(_searchQuery),
                  )
                  .toList();
              if (filtered.isEmpty)
                return const Center(child: Text("No users found."));
              return ListView.builder(
                itemCount: filtered.length,
                padding: const EdgeInsets.all(16),
                itemBuilder: (ctx, i) {
                  final user = filtered[i];
                  if (user.role == 'admin')
                    return ListTile(
                      title: Text(user.fullName),
                      subtitle: const Text("ADMIN"),
                    );
                  return Card(
                    color: user.isBanned ? Colors.red[50] : Colors.white,
                    child: ListTile(
                      leading: CircleAvatar(
                        backgroundColor: user.isBanned
                            ? Colors.red
                            : (user.role == 'doctor'
                                  ? Colors.blue
                                  : Colors.green),
                        child: Icon(
                          user.isBanned ? Icons.block : Icons.person,
                          color: Colors.white,
                        ),
                      ),
                      title: Text(
                        user.fullName,
                        style: TextStyle(
                          decoration: user.isBanned
                              ? TextDecoration.lineThrough
                              : null,
                        ),
                      ),
                      subtitle: Text(
                        "${user.email} • ${user.role.toUpperCase()}",
                      ),
                      trailing: ElevatedButton(
                        onPressed: () => _suspendUser(user.id),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: user.isBanned
                              ? Colors.green
                              : Colors.red,
                          foregroundColor: Colors.white,
                        ),
                        child: Text(user.isBanned ? "Unsuspend" : "Suspend"),
                      ),
                    ),
                  );
                },
              );
            },
          ),
        ),
      ],
    );
  }

  Widget _buildContentTab() {
    final contentAsync = ref.watch(adminContentProvider);
    return contentAsync.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => Text("$e"),
      data: (tips) => ListView.builder(
        itemCount: tips.length,
        padding: const EdgeInsets.all(16),
        itemBuilder: (ctx, i) => Card(
          margin: const EdgeInsets.only(bottom: 12),
          child: ListTile(
            title: Text(tips[i].title),
            trailing: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                IconButton(
                  icon: const Icon(Icons.edit, color: Colors.blue),
                  onPressed: () async {
                    final result = await Navigator.push(
                      context,
                      MaterialPageRoute(
                        builder: (_) =>
                            AdminContentEditorScreen(healthTip: tips[i]),
                      ),
                    );
                    if (result == true) ref.refresh(adminContentProvider);
                  },
                ),
                IconButton(
                  icon: const Icon(Icons.delete, color: Colors.red),
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
    );
  }
}

class _StatCard extends StatelessWidget {
  final String title, value;
  final Color color;
  final IconData icon;
  const _StatCard({
    required this.title,
    required this.value,
    required this.color,
    required this.icon,
  });
  @override
  Widget build(BuildContext context) {
    final width = (MediaQuery.of(context).size.width - 48) / 2;
    return Container(
      width: width,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border(left: BorderSide(color: color, width: 4)),
        boxShadow: [
          BoxShadow(color: Colors.grey.withOpacity(0.1), blurRadius: 5),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: color, size: 32),
          const SizedBox(height: 12),
          Text(
            value,
            style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
          ),
          Text(title, style: TextStyle(fontSize: 12, color: Colors.grey[600])),
        ],
      ),
    );
  }
}
