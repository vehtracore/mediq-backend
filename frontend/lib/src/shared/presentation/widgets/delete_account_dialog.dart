import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'package:mediq_app/src/features/auth/presentation/auth_controller.dart';

class DeleteAccountDialog extends ConsumerStatefulWidget {
  const DeleteAccountDialog({super.key});

  @override
  ConsumerState<DeleteAccountDialog> createState() => _DeleteAccountDialogState();
}

class _DeleteAccountDialogState extends ConsumerState<DeleteAccountDialog> {
  bool _isLoading = false;
  final TextEditingController _textController = TextEditingController();

  Future<void> _deleteAccount() async {
    if (_textController.text != "DELETE") return;

    setState(() {
      _isLoading = true;
    });

    try {
      final dio = ref.read(dioProvider);
      await dio.delete('/api/v1/auth/me/deactivate');

      await ref.read(authControllerProvider.notifier).logout();

      if (mounted) {
        context.go('/auth');
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _isLoading = false;
        });
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Failed to delete account: $e'),
            backgroundColor: Colors.red,
          ),
        );
      }
    }
  }

  @override
  void dispose() {
    _textController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Delete Account'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Text('Are you sure you want to delete your account? This action cannot be undone. Type "DELETE" below to confirm.'),
          const SizedBox(height: 16),
          TextField(
            controller: _textController,
            decoration: const InputDecoration(
              labelText: 'Type DELETE',
              border: OutlineInputBorder(),
            ),
            onChanged: (value) => setState(() {}),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: _isLoading ? null : () => Navigator.of(context).pop(),
          child: const Text('Cancel'),
        ),
        TextButton(
          onPressed: (_textController.text == "DELETE" && !_isLoading) ? _deleteAccount : null,
          child: _isLoading 
            ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2)) 
            : const Text('Permanently Delete', style: TextStyle(color: Colors.red)),
        ),
      ],
    );
  }
}
