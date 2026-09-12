import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import 'consultation_session_controller.dart';

class ConsultationChatPanel extends ConsumerStatefulWidget {
  const ConsultationChatPanel({
    super.key,
    required this.appointmentId,
  });

  final int appointmentId;

  @override
  ConsumerState<ConsultationChatPanel> createState() =>
      _ConsultationChatPanelState();
}

class _ConsultationChatPanelState extends ConsumerState<ConsultationChatPanel> {
  final TextEditingController _controller = TextEditingController();

  void _send(ConsultationSessionController session) {
    final text = _controller.text.trim();
    if (text.isEmpty) return;
    if (session.sendText(text)) {
      _controller.clear();
      return;
    }
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Chat is reconnecting. Try again shortly.')),
    );
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final session =
        ref.watch(consultationSessionProvider(widget.appointmentId));
    final colors = Theme.of(context).colorScheme;
    return SafeArea(
      top: false,
      child: SizedBox(
        height: MediaQuery.sizeOf(context).height * 0.72,
        child: Column(
          children: [
            const SizedBox(height: 10),
            Container(
              width: 42,
              height: 4,
              decoration: BoxDecoration(
                color: colors.outlineVariant,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 10, 8, 8),
              child: Row(
                children: [
                  const Expanded(
                    child: Text(
                      'Consultation chat',
                      style:
                          TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
                    ),
                  ),
                  IconButton(
                    tooltip: 'Close chat',
                    onPressed: () => Navigator.pop(context),
                    icon: const Icon(Icons.close),
                  ),
                ],
              ),
            ),
            if (session.connectionState !=
                ConsultationConnectionState.connected)
              Container(
                width: double.infinity,
                padding:
                    const EdgeInsets.symmetric(horizontal: 16, vertical: 7),
                color: colors.errorContainer,
                child: Text(
                  session.connectionState ==
                          ConsultationConnectionState.reconnecting
                      ? 'Chat is reconnecting'
                      : 'Chat is temporarily unavailable',
                  textAlign: TextAlign.center,
                ),
              ),
            Expanded(
              child: session.isLoading
                  ? const Center(child: CircularProgressIndicator())
                  : ListView.builder(
                      reverse: true,
                      padding: const EdgeInsets.symmetric(
                          horizontal: 16, vertical: 8),
                      itemCount: session.messages.length,
                      itemBuilder: (context, index) => _VideoChatMessage(
                        message: session.messages[index],
                        myUserId: session.myUserId,
                        appointmentId: widget.appointmentId,
                      ),
                    ),
            ),
            Padding(
              padding: EdgeInsets.fromLTRB(
                12,
                8,
                12,
                8 + MediaQuery.viewInsetsOf(context).bottom,
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Expanded(
                    child: TextField(
                      controller: _controller,
                      minLines: 1,
                      maxLines: 4,
                      textCapitalization: TextCapitalization.sentences,
                      decoration: const InputDecoration(
                        hintText: 'Message',
                        border: OutlineInputBorder(),
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  IconButton.filled(
                    tooltip: 'Send message',
                    onPressed: session.canSend ? () => _send(session) : null,
                    icon: const Icon(Icons.send),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _VideoChatMessage extends StatelessWidget {
  const _VideoChatMessage({
    required this.message,
    required this.myUserId,
    required this.appointmentId,
  });

  final Map<String, dynamic> message;
  final int? myUserId;
  final int appointmentId;

  @override
  Widget build(BuildContext context) {
    final content = message['content']?.toString() ?? '';
    if (content.contains('"type":"call_signal"')) {
      return const SizedBox.shrink();
    }
    final isMe = message['sender_id']?.toString() == myUserId?.toString();
    final attachment = _isAttachment(content);
    final createdAt =
        DateTime.tryParse(message['created_at']?.toString() ?? '');
    final colors = Theme.of(context).colorScheme;
    return Align(
      alignment: isMe ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        constraints:
            BoxConstraints(maxWidth: MediaQuery.sizeOf(context).width * 0.78),
        margin: const EdgeInsets.only(bottom: 8),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
        decoration: BoxDecoration(
          color: isMe ? colors.primary : colors.surfaceContainerHighest,
          borderRadius: BorderRadius.circular(8),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (attachment)
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    Icons.image_outlined,
                    size: 20,
                    color: isMe ? colors.onPrimary : colors.onSurfaceVariant,
                  ),
                  const SizedBox(width: 8),
                  Text(
                    'Image attachment',
                    style: TextStyle(
                      color: isMe ? colors.onPrimary : colors.onSurfaceVariant,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
              )
            else
              Text(
                content,
                style: TextStyle(
                    color: isMe ? colors.onPrimary : colors.onSurface),
              ),
            if (attachment)
              TextButton.icon(
                style: TextButton.styleFrom(
                  foregroundColor: isMe ? colors.onPrimary : colors.primary,
                  padding: EdgeInsets.zero,
                ),
                onPressed: () => context.push(
                  '/chat',
                  extra: {
                    'appointmentId': appointmentId,
                    'title': 'Consultation',
                    'isCompleted': false,
                  },
                ),
                icon: const Icon(Icons.open_in_full, size: 16),
                label: const Text('Open full chat'),
              ),
            if (createdAt != null)
              Padding(
                padding: const EdgeInsets.only(top: 3),
                child: Text(
                  DateFormat.jm().format(createdAt.toLocal()),
                  style: TextStyle(
                    fontSize: 10,
                    color: (isMe ? colors.onPrimary : colors.onSurfaceVariant)
                        .withValues(alpha: 0.75),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  bool _isAttachment(String content) =>
      content.startsWith('/static/') ||
      content.startsWith('http://') ||
      content.startsWith('https://') ||
      content.startsWith('FILE:');
}
