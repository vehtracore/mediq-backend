import 'package:flutter/material.dart';
import 'package:mediq_app/src/features/auth/data/auth_repository.dart';
import 'package:uuid/uuid.dart';

typedef SupportMessageSender = Future<SupportSubmissionResult> Function({
  required String requestId,
  required String subject,
  required String message,
});

class SupportContactSheet extends StatefulWidget {
  const SupportContactSheet({
    super.key,
    required this.onSend,
    this.createRequestId,
    this.initialSubject,
    this.onBack,
  });

  final SupportMessageSender onSend;
  final String Function()? createRequestId;
  final String? initialSubject;
  final VoidCallback? onBack;

  static String _newRequestId() => const Uuid().v4();

  @override
  State<SupportContactSheet> createState() => _SupportContactSheetState();
}

class _SupportContactSheetState extends State<SupportContactSheet> {
  static const _sendFailure =
      "We couldn't send your message right now. Your message hasn't been marked as sent. Please try again.";

  final _subjectController = TextEditingController();
  final _messageController = TextEditingController();
  String? _requestId;
  String? _attemptedSubject;
  String? _attemptedMessage;
  String? _errorText;
  bool _isLoading = false;

  @override
  void initState() {
    super.initState();
    _subjectController.text = widget.initialSubject ?? '';
    _subjectController.addListener(_draftChanged);
    _messageController.addListener(_draftChanged);
  }

  void _draftChanged() {
    if (_isLoading || _requestId == null) return;
    if (_subjectController.text.trim() == _attemptedSubject &&
        _messageController.text.trim() == _attemptedMessage) {
      return;
    }
    setState(() {
      _requestId = null;
      _errorText = null;
    });
  }

  Future<void> _submit() async {
    final subject = _subjectController.text.trim();
    final message = _messageController.text.trim();
    if (subject.isEmpty || message.isEmpty) {
      setState(() {
        _errorText = 'Enter both a subject and message.';
      });
      return;
    }

    final requestId = _requestId ??=
        (widget.createRequestId ?? SupportContactSheet._newRequestId)();
    _attemptedSubject = subject;
    _attemptedMessage = message;
    setState(() {
      _isLoading = true;
      _errorText = null;
    });

    try {
      final result = await widget.onSend(
        requestId: requestId,
        subject: subject,
        message: message,
      );
      if (!result.isSent || result.requestId != requestId) {
        throw StateError('Support delivery was not confirmed.');
      }
      _subjectController.clear();
      _messageController.clear();
      if (mounted) Navigator.of(context).pop(true);
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _isLoading = false;
        _errorText = _sendFailure;
      });
    }
  }

  @override
  void dispose() {
    _subjectController.dispose();
    _messageController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    return Padding(
      padding: EdgeInsets.only(
        bottom: MediaQuery.of(context).viewInsets.bottom,
        left: 24,
        right: 24,
        top: 24,
      ),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                if (widget.onBack != null)
                  IconButton(
                    tooltip: 'Back',
                    onPressed: widget.onBack,
                    icon: const Icon(Icons.arrow_back),
                  ),
                Text(
                  'Customer Service',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
              ],
            ),
            const SizedBox(height: 16),
            TextField(
              key: const Key('support-subject'),
              controller: _subjectController,
              enabled: !_isLoading,
              maxLength: 120,
              decoration: const InputDecoration(
                labelText: 'Subject',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 8),
            TextField(
              key: const Key('support-message'),
              controller: _messageController,
              enabled: !_isLoading,
              minLines: 3,
              maxLines: 5,
              maxLength: 5000,
              decoration: const InputDecoration(
                labelText: 'Message',
                border: OutlineInputBorder(),
              ),
            ),
            if (_errorText != null) ...[
              const SizedBox(height: 8),
              Text(
                _errorText!,
                key: const Key('support-error'),
                style: TextStyle(color: colorScheme.error),
              ),
            ],
            const SizedBox(height: 16),
            ElevatedButton.icon(
              key: const Key('support-submit'),
              onPressed: _isLoading ? null : _submit,
              icon: _isLoading
                  ? const SizedBox(
                      height: 18,
                      width: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.send_outlined),
              label: Text(_errorText == null ? 'Send Message' : 'Retry'),
            ),
            const SizedBox(height: 24),
          ],
        ),
      ),
    );
  }
}
