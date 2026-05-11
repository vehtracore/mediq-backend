import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter/services.dart';
import 'package:mediq_app/src/features/auth/data/auth_repository.dart';
import 'package:mediq_app/src/features/auth/presentation/user_controller.dart';
import 'package:mediq_app/src/features/auth/data/user_model.dart';

class FamilyDashboardScreen extends ConsumerStatefulWidget {
  const FamilyDashboardScreen({super.key});

  @override
  ConsumerState<FamilyDashboardScreen> createState() => _FamilyDashboardScreenState();
}

class _FamilyDashboardScreenState extends ConsumerState<FamilyDashboardScreen> {
  bool _isLoading = false;

  Future<void> _generateInvite() async {
    setState(() {
      _isLoading = true;
    });

    try {
      final inviteCode = await ref.read(authRepositoryProvider).generateFamilyInvite();
      if (!mounted) return;
      _showInviteCodeModal(inviteCode);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(e.toString().replaceAll('Exception: ', ''))),
      );
    } finally {
      if (mounted) {
        setState(() {
          _isLoading = false;
        });
      }
    }
  }

  void _showInviteCodeModal(String inviteCode) {
    showModalBottomSheet(
      context: context,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (context) {
        return Padding(
          padding: const EdgeInsets.all(24.0),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text(
                'Invite Family Member',
                style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 16),
              const Text(
                'Share this code with your family member. They can use it to join your family plan.',
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 24),
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: Colors.grey.withOpacity(0.1),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: Theme.of(context).primaryColor, width: 1),
                ),
                child: Text(
                  inviteCode,
                  style: const TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.bold,
                    letterSpacing: 1.5,
                  ),
                  textAlign: TextAlign.center,
                ),
              ),
              const SizedBox(height: 24),
              SizedBox(
                width: double.infinity,
                height: 50,
                child: ElevatedButton.icon(
                  onPressed: () {
                    Clipboard.setData(ClipboardData(text: inviteCode));
                    Navigator.pop(context);
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('Invite code copied to clipboard!')),
                    );
                  },
                  icon: const Icon(Icons.copy),
                  label: const Text('Copy to Clipboard'),
                ),
              ),
              const SizedBox(height: 16),
            ],
          ),
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final userAsync = ref.watch(userProvider);
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: const Text("Family Plan"),
      ),
      body: userAsync.when(
        data: (user) {
          if (user == null) {
            return const Center(child: Text("Unable to load user data"));
          }

          final dependents = user.dependents;
          final int seatsUsed = 1 + dependents.length; // 1 for primary + dependents
          final int totalSeats = 5;

          return Padding(
            padding: const EdgeInsets.all(24.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Header & Progress
                Container(
                  padding: const EdgeInsets.all(20),
                  decoration: BoxDecoration(
                    color: theme.cardTheme.color,
                    borderRadius: BorderRadius.circular(16),
                    boxShadow: [
                      if (theme.brightness == Brightness.light)
                        BoxShadow(
                          color: Colors.grey.withOpacity(0.1),
                          blurRadius: 10,
                          offset: const Offset(0, 5),
                        ),
                    ],
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          const Text(
                            "Seats Used",
                            style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                          ),
                          Text(
                            "$seatsUsed / $totalSeats",
                            style: TextStyle(
                              fontSize: 16,
                              fontWeight: FontWeight.bold,
                              color: theme.primaryColor,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 12),
                      LinearProgressIndicator(
                        value: seatsUsed / totalSeats,
                        backgroundColor: Colors.grey.withOpacity(0.2),
                        color: theme.primaryColor,
                        minHeight: 8,
                        borderRadius: BorderRadius.circular(4),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 32),

                // Action Button
                if (seatsUsed < totalSeats)
                  SizedBox(
                    width: double.infinity,
                    height: 54,
                    child: ElevatedButton.icon(
                      onPressed: _isLoading ? null : _generateInvite,
                      icon: _isLoading
                          ? const SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                            )
                          : const Icon(Icons.person_add),
                      label: Text(_isLoading ? 'Generating...' : 'Invite Family Member'),
                      style: ElevatedButton.styleFrom(
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                      ),
                    ),
                  )
                else
                  Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: Colors.amber.withOpacity(0.1),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: Colors.amber),
                    ),
                    child: const Row(
                      children: [
                        Icon(Icons.info_outline, color: Colors.amber),
                        SizedBox(width: 12),
                        Expanded(
                          child: Text(
                            "Your family plan is full. You cannot invite more members.",
                            style: TextStyle(color: Colors.amber),
                          ),
                        ),
                      ],
                    ),
                  ),
                const SizedBox(height: 32),

                // Dependents List
                const Text(
                  "Linked Dependents",
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                ),
                const SizedBox(height: 16),
                if (dependents.isEmpty)
                  Center(
                    child: Padding(
                      padding: const EdgeInsets.all(32.0),
                      child: Column(
                        children: [
                          Icon(Icons.group_outlined, size: 64, color: Colors.grey.withOpacity(0.5)),
                          const SizedBox(height: 16),
                          const Text(
                            "No family members linked yet.",
                            style: TextStyle(color: Colors.grey),
                          ),
                        ],
                      ),
                    ),
                  )
                else
                  Expanded(
                    child: ListView.separated(
                      itemCount: dependents.length,
                      separatorBuilder: (context, index) => const Divider(),
                      itemBuilder: (context, index) {
                        final dependent = dependents[index];
                        return ListTile(
                          leading: CircleAvatar(
                            backgroundImage: dependent.imageUrl.isNotEmpty
                                ? NetworkImage(dependent.imageUrl)
                                : null,
                            child: dependent.imageUrl.isEmpty
                                ? Text(dependent.firstName.isNotEmpty
                                    ? dependent.firstName[0].toUpperCase()
                                    : '?')
                                : null,
                          ),
                          title: Text("${dependent.firstName} ${dependent.lastName}"),
                          subtitle: Text(dependent.email),
                          trailing: Container(
                            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                            decoration: BoxDecoration(
                              color: theme.primaryColor.withOpacity(0.1),
                              borderRadius: BorderRadius.circular(8),
                            ),
                            child: Text(
                              "Dependent",
                              style: TextStyle(fontSize: 12, color: theme.primaryColor),
                            ),
                          ),
                        );
                      },
                    ),
                  ),
              ],
            ),
          );
        },
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, stack) => Center(child: Text("Error: $error")),
      ),
    );
  }
}
