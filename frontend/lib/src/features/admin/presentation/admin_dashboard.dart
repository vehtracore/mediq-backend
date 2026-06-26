import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'package:mediq_app/src/features/auth/presentation/auth_controller.dart';
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

final adminPayoutsProvider = FutureProvider.autoDispose
    .family<List<dynamic>, String>((ref, status) async {
  final dio = ref.watch(dioProvider);
  final response = await dio.get(
    '/api/v1/admin/payouts',
    queryParameters: {'payout_status': status},
  );
  return List<dynamic>.from(response.data as List);
});

final adminRefundsProvider = FutureProvider.autoDispose
    .family<List<dynamic>, String>((ref, status) async {
  final dio = ref.watch(dioProvider);
  final response = await dio.get(
    '/api/v1/admin/refunds',
    queryParameters: {'refund_status': status},
  );
  return List<dynamic>.from(response.data as List);
});

class AdminDashboard extends ConsumerStatefulWidget {
  const AdminDashboard({super.key});
  @override
  ConsumerState<AdminDashboard> createState() => _AdminDashboardState();
}

class _AdminDashboardState extends ConsumerState<AdminDashboard> {
  final TextEditingController _searchCtrl = TextEditingController();
  String _searchQuery = "";
  String _payoutStatus = "awaiting_admin";
  String _refundStatus = "awaiting_admin";

  @override
  void dispose() {
    _searchCtrl.dispose();
    super.dispose();
  }

  Future<void> _verifyDoctor(int id) async {
    try {
      await ref.read(dioProvider).put('/api/v1/admin/doctors/$id/verify');
      // Ã¢Å“â€¦ FIX: Use invalidate() Ã¢â‚¬â€ consistent with _rejectDoctor
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
      // Ã¢Å“â€¦ FIX: Use invalidate() Ã¢â‚¬â€ the correct method for autoDispose providers.
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
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text("Reject failed: $e"), backgroundColor: Colors.red));
      }
    }
  }

  Future<void> _suspendUser(String id) async {
    try {
      await ref.read(dioProvider).put('/api/v1/admin/users/$id/suspend');
      ref.invalidate(allUsersProvider);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text("User Status Updated"),
            backgroundColor: Colors.blue));
      }
    } catch (e) {}
  }

  Future<void> _approvePayout(int payoutId) async {
    try {
      await ref
          .read(dioProvider)
          .put('/api/v1/admin/payouts/$payoutId/approve');
      ref.invalidate(adminPayoutsProvider);
      ref.invalidate(adminStatsProvider);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text("Payout approved for processing."),
          backgroundColor: Colors.green,
        ));
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text("Could not approve payout. Please try again."),
          backgroundColor: Colors.red,
        ));
      }
    }
  }

  Future<void> _rejectPayout(int payoutId, String reason) async {
    try {
      await ref.read(dioProvider).put(
        '/api/v1/admin/payouts/$payoutId/reject',
        data: {'rejection_reason': reason},
      );
      ref.invalidate(adminPayoutsProvider);
      ref.invalidate(adminStatsProvider);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text("Payout rejected."),
          backgroundColor: Colors.orange,
        ));
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text("Could not reject payout. Please try again."),
          backgroundColor: Colors.red,
        ));
      }
    }
  }

  Future<void> _approveRefund(int appointmentId) async {
    try {
      await ref
          .read(dioProvider)
          .put('/api/v1/admin/refunds/$appointmentId/approve');
      ref.invalidate(adminRefundsProvider);
      ref.invalidate(adminStatsProvider);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text("Refund approved for processing."),
          backgroundColor: Colors.green,
        ));
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text("Could not approve refund. Please try again."),
          backgroundColor: Colors.red,
        ));
      }
    }
  }

  Future<void> _rejectRefund(int appointmentId, String reason) async {
    try {
      await ref.read(dioProvider).put(
        '/api/v1/admin/refunds/$appointmentId/reject',
        data: {'rejection_reason': reason},
      );
      ref.invalidate(adminRefundsProvider);
      ref.invalidate(adminStatsProvider);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text("Refund rejected."),
          backgroundColor: Colors.orange,
        ));
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text("Could not reject refund. Please try again."),
          backgroundColor: Colors.red,
        ));
      }
    }
  }

  String _formatTimestamp(dynamic value) {
    if (value == null) return "Not recorded";
    final parsed = DateTime.tryParse(value.toString());
    if (parsed == null) return "Not recorded";
    final local = parsed.toLocal();
    String two(int number) => number.toString().padLeft(2, '0');
    return "${two(local.day)}/${two(local.month)}/${local.year} "
        "${two(local.hour)}:${two(local.minute)}";
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
      length: 6,
      child: Scaffold(
        backgroundColor:
            theme.scaffoldBackgroundColor, // Ã¢Å“â€¦ Dynamic Background
        appBar: AppBar(
          title: const Text("Admin Console",
              style: TextStyle(fontWeight: FontWeight.bold)),
          backgroundColor: isDark
              ? const Color(0xFF1E1E1E)
              : Colors.blueGrey[900], // Ã¢Å“â€¦ Darker header in dark mode
          foregroundColor: Colors.white,
          bottom: const TabBar(
            isScrollable: true,
            indicatorColor: Colors.orange,
            labelColor: Colors.white,
            unselectedLabelColor: Colors.white70,
            tabs: [
              Tab(icon: Icon(Icons.dashboard), text: "Overview"),
              Tab(icon: Icon(Icons.verified_user), text: "Verifications"),
              Tab(icon: Icon(Icons.payments), text: "Payouts"),
              Tab(icon: Icon(Icons.replay), text: "Refunds"),
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
            _buildPayoutsTab(),
            _buildRefundsTab(),
            _buildUsersTab(),
            _buildContentTab(),
          ],
        ),
        floatingActionButton: Builder(
          builder: (tabContext) {
            final tabController = DefaultTabController.of(tabContext);
            return AnimatedBuilder(
              animation: tabController,
              builder: (context, _) => tabController.index == 5
                  ? FloatingActionButton(
                      backgroundColor: Colors.orange,
                      child: const Icon(Icons.add),
                      onPressed: () async {
                        final result = await Navigator.push(
                          context,
                          MaterialPageRoute(
                            builder: (_) => const AdminContentEditorScreen(),
                          ),
                        );
                        if (result == true) {
                          ref.invalidate(adminContentProvider);
                        }
                      },
                    )
                  : const SizedBox.shrink(),
            );
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
            child: SkeletonLoader(
                child: Container(
                    height: 100,
                    width: double.infinity,
                    decoration: BoxDecoration(
                        color: Colors.white,
                        borderRadius: BorderRadius.circular(12)))),
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
                      title: "Total Consultations",
                      value: "${stats['total_completed_consultations'] ?? 0}",
                      color: Colors.green,
                      icon: Icons.assignment_turned_in),
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
                  _StatCard(
                      title: "Payout Reviews",
                      value: "${stats['pending_payout_approvals'] ?? 0}",
                      color: Colors.indigo,
                      icon: Icons.payments),
                  _StatCard(
                      title: "Refund Reviews",
                      value: "${stats['pending_refund_approvals'] ?? 0}",
                      color: Colors.deepOrange,
                      icon: Icons.replay),
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
            child: SkeletonLoader(
                child: Container(
                    height: 100,
                    width: double.infinity,
                    decoration: BoxDecoration(
                        color: Colors.white,
                        borderRadius: BorderRadius.circular(12)))),
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
                    child:
                        const Center(child: Text("No pending verifications.")),
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
                    color: theme.cardTheme.color, // Ã¢Å“â€¦ Dynamic Card
                    child: Column(
                      children: [
                        ListTile(
                          leading: const CircleAvatar(
                              child: Icon(Icons.local_hospital)),
                          title: Text(doctors[i]['full_name'],
                              style: theme.textTheme.bodyLarge),
                          subtitle: Text(
                              doctors[i]['specialty'] ?? "Specialist",
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
                                    backgroundColor: theme.colorScheme.primary
                                        .withOpacity(0.15),
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
                                            onPressed: () =>
                                                Navigator.pop(context),
                                            child: const Text("Cancel"),
                                          ),
                                          ElevatedButton(
                                            onPressed: () {
                                              final reason =
                                                  reasonCtrl.text.trim();
                                              if (reason.isNotEmpty) {
                                                Navigator.pop(context);
                                                _rejectDoctor(
                                                    doctors[i]['id'], reason);
                                              }
                                            },
                                            style: ElevatedButton.styleFrom(
                                                backgroundColor: Colors.red,
                                                foregroundColor: Colors.white),
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
                                    backgroundColor: theme.colorScheme.primary
                                        .withOpacity(0.15),
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

  Widget _buildPayoutsTab() {
    final payoutsAsync = ref.watch(adminPayoutsProvider(_payoutStatus));
    final theme = Theme.of(context);

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
          child: DropdownButtonFormField<String>(
            initialValue: _payoutStatus,
            decoration: const InputDecoration(labelText: "Payout status"),
            items: const [
              DropdownMenuItem(
                  value: "awaiting_admin", child: Text("Awaiting approval")),
              DropdownMenuItem(value: "approved", child: Text("Approved")),
              DropdownMenuItem(value: "processing", child: Text("Processing")),
              DropdownMenuItem(value: "blocked", child: Text("Blocked")),
              DropdownMenuItem(value: "failed", child: Text("Failed")),
              DropdownMenuItem(value: "paid", child: Text("Paid")),
              DropdownMenuItem(value: "rejected", child: Text("Rejected")),
              DropdownMenuItem(value: "reversed", child: Text("Reversed")),
            ],
            onChanged: (value) {
              if (value != null) setState(() => _payoutStatus = value);
            },
          ),
        ),
        Expanded(
          child: RefreshIndicator(
            onRefresh: () async =>
                ref.invalidate(adminPayoutsProvider(_payoutStatus)),
            child: payoutsAsync.when(
              loading: () => ListView.builder(
                physics: const AlwaysScrollableScrollPhysics(),
                padding: const EdgeInsets.all(16),
                itemCount: 4,
                itemBuilder: (context, index) => Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: SkeletonLoader(
                    child: Container(
                      height: 180,
                      decoration: BoxDecoration(
                        color: Colors.white,
                        borderRadius: BorderRadius.circular(12),
                      ),
                    ),
                  ),
                ),
              ),
              error: (error, _) => ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                children: [
                  SizedBox(
                    height: MediaQuery.of(context).size.height * 0.7,
                    child: GlobalErrorWidget(
                      error: error,
                      onRetry: () =>
                          ref.invalidate(adminPayoutsProvider(_payoutStatus)),
                    ),
                  ),
                ],
              ),
              data: (payouts) {
                if (payouts.isEmpty) {
                  return ListView(
                    physics: const AlwaysScrollableScrollPhysics(),
                    children: [
                      SizedBox(
                        height: MediaQuery.of(context).size.height * 0.7,
                        child: Center(
                          child: Text(
                              "No ${_payoutStatus.replaceAll('_', ' ')} payouts."),
                        ),
                      ),
                    ],
                  );
                }

                return ListView.builder(
                  physics: const AlwaysScrollableScrollPhysics(),
                  padding: const EdgeInsets.all(16),
                  itemCount: payouts.length,
                  itemBuilder: (context, index) {
                    final payout =
                        Map<String, dynamic>.from(payouts[index] as Map);
                    final payoutId = payout['id'] as int;
                    final amount = (payout['amount'] as num?)?.toDouble() ?? 0;
                    final bankReady = payout['bank_ready'] == true;
                    final awaitingApproval =
                        payout['status'] == "awaiting_admin";
                    final holdElapsed = payout['payout_hold_elapsed'] == true;
                    final blockedByReview =
                        payout['payout_blocked_by_refund_or_dispute'] == true;
                    final canApprove =
                        bankReady && holdElapsed && !blockedByReview;

                    return Card(
                      color: theme.cardTheme.color,
                      margin: const EdgeInsets.only(bottom: 14),
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                const CircleAvatar(child: Icon(Icons.payments)),
                                const SizedBox(width: 12),
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        payout['doctor_name'] ?? "Doctor",
                                        style: theme.textTheme.titleMedium
                                            ?.copyWith(
                                          fontWeight: FontWeight.bold,
                                        ),
                                      ),
                                      Text(
                                        "Patient: ${payout['patient_name'] ?? 'Unknown'}"
                                        " Ã¢â‚¬Â¢ Appointment #${payout['appointment_id']}",
                                      ),
                                    ],
                                  ),
                                ),
                                Text(
                                  "Ã¢â€šÂ¦${amount.toStringAsFixed(2)}",
                                  style: theme.textTheme.titleMedium?.copyWith(
                                    fontWeight: FontWeight.bold,
                                    color: Colors.green,
                                  ),
                                ),
                              ],
                            ),
                            const Divider(height: 24),
                            Text(
                              "Outcome: ${payout['appointment_status'] ?? 'Unknown'}"
                              " Ã¢â‚¬Â¢ Payment: ${payout['payment_status'] ?? 'Unknown'}",
                            ),
                            const SizedBox(height: 6),
                            Text(
                              "Payout status: ${payout['status'] ?? 'Unknown'}",
                              style:
                                  const TextStyle(fontWeight: FontWeight.w600),
                            ),
                            const SizedBox(height: 6),
                            Text(
                              "Type: ${payout['appointment_type'] ?? 'Unknown'}"
                              " - Refund/dispute: ${payout['refund_status'] ?? 'none'}",
                            ),
                            const SizedBox(height: 6),
                            Text(
                              holdElapsed
                                  ? "24-hour complaint hold elapsed"
                                  : "Held until: ${_formatTimestamp(payout['payout_hold_until'])}",
                              style: TextStyle(
                                color:
                                    holdElapsed ? Colors.green : Colors.orange,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                            if (blockedByReview) ...[
                              const SizedBox(height: 6),
                              const Text(
                                "Blocked by refund/dispute review",
                                style: TextStyle(
                                  color: Colors.red,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ],
                            const SizedBox(height: 6),
                            Text(
                              bankReady
                                  ? "Bank payout details ready"
                                  : "Doctor must complete bank payout settings",
                              style: TextStyle(
                                color: bankReady ? Colors.green : Colors.orange,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                            const SizedBox(height: 10),
                            Text(
                              "Patient joined: "
                              "${_formatTimestamp(payout['patient_joined_at'])}",
                            ),
                            Text(
                              "Doctor joined: "
                              "${_formatTimestamp(payout['doctor_joined_at'])}",
                            ),
                            Text(
                              "Session started: "
                              "${_formatTimestamp(payout['consultation_started_at'])}",
                            ),
                            const SizedBox(height: 14),
                            if (awaitingApproval)
                              Row(
                                mainAxisAlignment: MainAxisAlignment.end,
                                children: [
                                  TextButton.icon(
                                    icon: const Icon(Icons.close,
                                        color: Colors.red),
                                    label: const Text("Reject"),
                                    onPressed: () {
                                      final reasonController =
                                          TextEditingController();
                                      showDialog<void>(
                                        context: context,
                                        builder: (dialogContext) => AlertDialog(
                                          title: const Text("Reject payout"),
                                          content: TextField(
                                            controller: reasonController,
                                            maxLength: 1000,
                                            maxLines: 3,
                                            decoration: const InputDecoration(
                                              hintText: "Reason for rejection",
                                            ),
                                          ),
                                          actions: [
                                            TextButton(
                                              onPressed: () =>
                                                  Navigator.pop(dialogContext),
                                              child: const Text("Cancel"),
                                            ),
                                            ElevatedButton(
                                              onPressed: () {
                                                final reason = reasonController
                                                    .text
                                                    .trim();
                                                if (reason.isEmpty) return;
                                                Navigator.pop(dialogContext);
                                                _rejectPayout(payoutId, reason);
                                              },
                                              style: ElevatedButton.styleFrom(
                                                backgroundColor: Colors.red,
                                                foregroundColor: Colors.white,
                                              ),
                                              child: const Text("Reject"),
                                            ),
                                          ],
                                        ),
                                      ).whenComplete(reasonController.dispose);
                                    },
                                  ),
                                  const SizedBox(width: 8),
                                  ElevatedButton.icon(
                                    icon: const Icon(Icons.check),
                                    label: const Text("Approve"),
                                    onPressed: canApprove
                                        ? () => _approvePayout(payoutId)
                                        : null,
                                  ),
                                ],
                              ),
                          ],
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

  Widget _buildRefundsTab() {
    final refundsAsync = ref.watch(adminRefundsProvider(_refundStatus));
    final theme = Theme.of(context);

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
          child: DropdownButtonFormField<String>(
            initialValue: _refundStatus,
            decoration: const InputDecoration(labelText: "Refund status"),
            items: const [
              DropdownMenuItem(
                  value: "awaiting_admin", child: Text("Awaiting approval")),
              DropdownMenuItem(value: "approved", child: Text("Approved")),
              DropdownMenuItem(value: "pending", child: Text("Pending")),
              DropdownMenuItem(value: "processing", child: Text("Processing")),
              DropdownMenuItem(
                  value: "needs_attention", child: Text("Needs attention")),
              DropdownMenuItem(
                  value: "verification_required",
                  child: Text("Verify in Paystack")),
              DropdownMenuItem(value: "processed", child: Text("Processed")),
              DropdownMenuItem(value: "failed", child: Text("Failed")),
              DropdownMenuItem(value: "rejected", child: Text("Rejected")),
            ],
            onChanged: (value) {
              if (value != null) setState(() => _refundStatus = value);
            },
          ),
        ),
        Expanded(
          child: RefreshIndicator(
            onRefresh: () async =>
                ref.invalidate(adminRefundsProvider(_refundStatus)),
            child: refundsAsync.when(
              loading: () => ListView.builder(
                physics: const AlwaysScrollableScrollPhysics(),
                padding: const EdgeInsets.all(16),
                itemCount: 4,
                itemBuilder: (context, index) => const Padding(
                  padding: EdgeInsets.only(bottom: 12),
                  child: SkeletonLoader(
                    child: SizedBox(height: 170),
                  ),
                ),
              ),
              error: (error, _) => ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                children: [
                  SizedBox(
                    height: MediaQuery.of(context).size.height * 0.7,
                    child: GlobalErrorWidget(
                      error: error,
                      onRetry: () =>
                          ref.invalidate(adminRefundsProvider(_refundStatus)),
                    ),
                  ),
                ],
              ),
              data: (refunds) {
                if (refunds.isEmpty) {
                  return ListView(
                    physics: const AlwaysScrollableScrollPhysics(),
                    children: [
                      SizedBox(
                        height: MediaQuery.of(context).size.height * 0.7,
                        child: Center(
                          child: Text(
                            "No ${_refundStatus.replaceAll('_', ' ')} refunds.",
                          ),
                        ),
                      ),
                    ],
                  );
                }

                return ListView.builder(
                  physics: const AlwaysScrollableScrollPhysics(),
                  padding: const EdgeInsets.all(16),
                  itemCount: refunds.length,
                  itemBuilder: (context, index) {
                    final refund =
                        Map<String, dynamic>.from(refunds[index] as Map);
                    final appointmentId = refund['appointment_id'] as int;
                    final amount =
                        (refund['refund_amount'] as num?)?.toDouble() ?? 0;
                    final awaitingApproval =
                        refund['refund_status'] == "awaiting_admin";

                    return Card(
                      color: theme.cardTheme.color,
                      margin: const EdgeInsets.only(bottom: 14),
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                const CircleAvatar(child: Icon(Icons.replay)),
                                const SizedBox(width: 12),
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        refund['patient_name'] ?? "Patient",
                                        style: theme.textTheme.titleMedium
                                            ?.copyWith(
                                          fontWeight: FontWeight.bold,
                                        ),
                                      ),
                                      Text(
                                        "Doctor: ${refund['doctor_name']}"
                                        " Ã¢â‚¬Â¢ Appointment #$appointmentId",
                                      ),
                                    ],
                                  ),
                                ),
                                Text(
                                  "NGN ${amount.toStringAsFixed(2)}",
                                  style: theme.textTheme.titleMedium?.copyWith(
                                    fontWeight: FontWeight.bold,
                                    color: Colors.deepOrange,
                                  ),
                                ),
                              ],
                            ),
                            const Divider(height: 24),
                            Text(
                              "Outcome: ${refund['appointment_status']}"
                              " Ã¢â‚¬Â¢ Refund: ${refund['refund_status']}",
                            ),
                            Text(
                              "Patient joined: "
                              "${_formatTimestamp(refund['patient_joined_at'])}",
                            ),
                            Text(
                              "Doctor joined: "
                              "${_formatTimestamp(refund['doctor_joined_at'])}",
                            ),
                            if (refund['refund_last_error'] != null) ...[
                              const SizedBox(height: 8),
                              Text(
                                refund['refund_last_error'].toString(),
                                style: const TextStyle(color: Colors.red),
                              ),
                            ],
                            if (awaitingApproval) ...[
                              const SizedBox(height: 14),
                              Row(
                                mainAxisAlignment: MainAxisAlignment.end,
                                children: [
                                  TextButton.icon(
                                    icon: const Icon(
                                      Icons.close,
                                      color: Colors.red,
                                    ),
                                    label: const Text("Reject"),
                                    onPressed: () {
                                      final controller =
                                          TextEditingController();
                                      showDialog<void>(
                                        context: context,
                                        builder: (dialogContext) => AlertDialog(
                                          title: const Text("Reject refund"),
                                          content: TextField(
                                            controller: controller,
                                            maxLength: 1000,
                                            maxLines: 3,
                                            decoration: const InputDecoration(
                                              hintText: "Reason for rejection",
                                            ),
                                          ),
                                          actions: [
                                            TextButton(
                                              onPressed: () =>
                                                  Navigator.pop(dialogContext),
                                              child: const Text("Cancel"),
                                            ),
                                            ElevatedButton(
                                              onPressed: () {
                                                final reason =
                                                    controller.text.trim();
                                                if (reason.isEmpty) return;
                                                Navigator.pop(dialogContext);
                                                _rejectRefund(
                                                  appointmentId,
                                                  reason,
                                                );
                                              },
                                              style: ElevatedButton.styleFrom(
                                                backgroundColor: Colors.red,
                                                foregroundColor: Colors.white,
                                              ),
                                              child: const Text("Reject"),
                                            ),
                                          ],
                                        ),
                                      ).whenComplete(controller.dispose);
                                    },
                                  ),
                                  const SizedBox(width: 8),
                                  ElevatedButton.icon(
                                    icon: const Icon(Icons.check),
                                    label: const Text("Approve refund"),
                                    onPressed: () =>
                                        _approveRefund(appointmentId),
                                  ),
                                ],
                              ),
                            ],
                          ],
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

  Widget _buildUsersTab() {
    final usersAsync = ref.watch(allUsersProvider);
    final theme = Theme.of(context);

    return Column(
      children: [
        Container(
          padding: const EdgeInsets.all(16),
          color: theme.cardTheme.color, // Ã¢Å“â€¦ Dynamic Search Bar Background
          child: TextField(
            controller: _searchCtrl,
            style: theme.textTheme.bodyLarge, // Ã¢Å“â€¦ Text color
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
                  child: SkeletonLoader(
                      child: Container(
                          height: 70,
                          width: double.infinity,
                          decoration: BoxDecoration(
                              color: Colors.white,
                              borderRadius: BorderRadius.circular(12)))),
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
                    final isBanned = user.isBanned; // Ã¢Å“â€¦ Dynamic status

                    if (user.role == 'admin') {
                      return ListTile(
                          title: Text(fullName), subtitle: const Text("ADMIN"));
                    }

                    // Ã¢Å“â€¦ Dynamic Card Logic for Banned/Normal users
                    final cardColor = isBanned
                        ? (theme.brightness == Brightness.dark
                            ? Colors.red.withOpacity(0.2)
                            : Colors.red[50])
                        : theme.cardTheme.color;

                    return Card(
                      color: cardColor,
                      child: ListTile(
                        leading: CircleAvatar(
                          backgroundColor: user.role == 'doctor'
                              ? Colors.blue
                              : Colors.green,
                          child: const Icon(Icons.person, color: Colors.white),
                        ),
                        title: Text(fullName, style: theme.textTheme.bodyLarge),
                        subtitle: Text(
                            "${user.email} Ã¢â‚¬Â¢ ${user.role.toUpperCase()}",
                            style: theme.textTheme.bodyMedium),
                        trailing: IconButton.filledTonal(
                          onPressed: () => _suspendUser(user.id),
                          icon: Icon(isBanned
                              ? Icons.check_circle_outline
                              : Icons.block),
                          tooltip: isBanned ? "Reactivate" : "Suspend",
                          style: IconButton.styleFrom(
                            backgroundColor:
                                theme.colorScheme.primary.withOpacity(0.15),
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
            child: SkeletonLoader(
                child: Container(
                    height: 80,
                    width: double.infinity,
                    decoration: BoxDecoration(
                        color: Colors.white,
                        borderRadius: BorderRadius.circular(12)))),
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
            color: theme.cardTheme.color, // Ã¢Å“â€¦ Dynamic Card
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
                      backgroundColor:
                          theme.colorScheme.primary.withOpacity(0.15),
                      foregroundColor: theme.colorScheme.primary,
                      elevation: 0,
                    ),
                    onPressed: () async {
                      final result = await Navigator.push(
                          context,
                          MaterialPageRoute(
                              builder: (_) => AdminContentEditorScreen(
                                  healthTip: tips[i])));
                      if (result == true) ref.invalidate(adminContentProvider);
                    },
                  ),
                  const SizedBox(width: 8),
                  IconButton.filledTonal(
                    icon: const Icon(Icons.delete, size: 20),
                    tooltip: "Delete",
                    style: IconButton.styleFrom(
                      backgroundColor:
                          theme.colorScheme.primary.withOpacity(0.15),
                      foregroundColor: theme.colorScheme.primary,
                      elevation: 0,
                    ),
                    onPressed: () async {
                      await ref
                          .read(contentRepositoryProvider)
                          .deleteHealthTip(tips[i].id);
                      ref.invalidate(adminContentProvider);
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
        color: theme.cardTheme.color, // Ã¢Å“â€¦ Dynamic Card Background
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
