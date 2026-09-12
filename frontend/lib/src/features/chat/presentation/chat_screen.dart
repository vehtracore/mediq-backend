import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';

import '../../../core/api/dio_client.dart';
import '../../auth/presentation/profile_recovery_view.dart';
import '../../auth/presentation/user_controller.dart';
import '../../doctors/data/doctor_repository.dart';
import '../data/image_upload_service.dart';
import 'consultation_countdown_badge.dart';
import 'consultation_session_controller.dart';

class ChatScreen extends ConsumerStatefulWidget {
  const ChatScreen({
    super.key,
    required this.appointmentId,
    required this.title,
    this.isCompleted = false,
    this.doctorId,
  });

  final int appointmentId;
  final String title;
  final bool isCompleted;
  final int? doctorId;

  @override
  ConsumerState<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends ConsumerState<ChatScreen> {
  final TextEditingController _messageController = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  late final ConsultationSessionController _session;
  String? _mdcnNumber;

  @override
  void initState() {
    super.initState();
    _session = ref.read(consultationSessionProvider(widget.appointmentId));
    _session.attachChatSurface();
    unawaited(_session.ensureStarted(live: !widget.isCompleted));
    unawaited(_loadDoctorDetails());
    _scrollController.addListener(_handleScroll);
  }

  Future<void> _loadDoctorDetails() async {
    final doctorId = widget.doctorId;
    if (doctorId == null) return;
    try {
      final doctor =
          await ref.read(doctorRepositoryProvider).getDoctorById(doctorId);
      if (mounted && doctor.licenseNumber?.isNotEmpty == true) {
        setState(() => _mdcnNumber = doctor.licenseNumber);
      }
    } catch (_) {
      // Doctor metadata is optional; consultation access remains server-owned.
    }
  }

  void _handleScroll() {
    if (!_scrollController.hasClients) return;
    if (_scrollController.position.pixels >=
        _scrollController.position.maxScrollExtent - 200) {
      unawaited(_session.fetchMoreMessages());
    }
  }

  void _sendMessage() {
    final text = _messageController.text.trim();
    if (text.isEmpty) return;
    if (_session.sendText(text)) {
      _messageController.clear();
      return;
    }
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Chat is reconnecting. Try again shortly.')),
    );
  }

  Future<void> _handleImageUpload() async {
    final picker = ImagePicker();
    final image = await picker.pickImage(
      source: ImageSource.gallery,
      imageQuality: 90,
      maxWidth: 1920,
      maxHeight: 1920,
    );
    if (image == null) return;

    final optimisticId = _session.addOptimisticMessage('FILE:${image.path}');
    final url = await ref.read(imageUploadServiceProvider).uploadFile(image);
    if (url == null) {
      _session.removeOptimisticMessage(optimisticId);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Image upload failed')),
        );
      }
      return;
    }
    _session.updateOptimisticMessage(optimisticId, url);
    if (!_session.sendText(url, optimisticId: optimisticId) && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Failed to send image')),
      );
    }
  }

  Future<void> _openVideo({bool voice = false}) async {
    _session.sendCallSignal(voice ? 'audio' : 'video');
    _session.setChatSurfaceVisible(false);
    _session.beginVideoTransition();
    await context.push(
      voice ? '/video_call?type=voice' : '/video_call',
      extra: widget.appointmentId,
    );
    if (!mounted) return;
    _session.leaveVideo(returningToChat: true);
    _session.setChatSurfaceVisible(true);
  }

  @override
  void dispose() {
    _session.detachChatSurface();
    _messageController.dispose();
    _scrollController
      ..removeListener(_handleScroll)
      ..dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final session =
        ref.watch(consultationSessionProvider(widget.appointmentId));
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;
    final baseUrl = ref.watch(dioProvider).options.baseUrl;
    final cleanBaseUrl = baseUrl.endsWith('/')
        ? baseUrl.substring(0, baseUrl.length - 1)
        : baseUrl;

    return Scaffold(
      backgroundColor: theme.colorScheme.surface,
      body: Column(
        children: [
          _ChatHeader(
            title: widget.title,
            mdcnNumber: _mdcnNumber,
            session: session,
            onBack: context.pop,
            onVoice:
                session.canStartCall ? () => _openVideo(voice: true) : null,
            onVideo: session.canStartCall ? _openVideo : null,
          ),
          if (session.peerMode == ConsultationMode.videoWaiting)
            _JoinVideoBanner(
              participant: session.peerParticipantLabel,
              onJoin: session.canStartCall ? _openVideo : null,
            ),
          Expanded(
            child: session.initializationError != null
                ? AuthenticatedProfileRecoveryView(
                    error: session.initializationError,
                    onRetry: () {
                      ref.invalidate(userProvider);
                      unawaited(session.retry());
                    },
                  )
                : session.isLoading
                    ? const Center(child: CircularProgressIndicator())
                    : ListView.builder(
                        controller: _scrollController,
                        reverse: true,
                        padding: const EdgeInsets.all(16),
                        itemCount: session.messages.length +
                            (session.isLoadingMore ? 1 : 0),
                        itemBuilder: (context, index) {
                          if (index == session.messages.length) {
                            return const Padding(
                              padding: EdgeInsets.symmetric(vertical: 16),
                              child: Center(child: CircularProgressIndicator()),
                            );
                          }
                          return _FullChatMessageBubble(
                            message: session.messages[index],
                            myUserId: session.myUserId,
                            cleanBaseUrl: cleanBaseUrl,
                            theme: theme,
                          );
                        },
                      ),
          ),
          if (widget.isCompleted || session.isConsultationClosed)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
              color: theme.cardTheme.color,
              width: double.infinity,
              child: const SafeArea(
                child: Text(
                  'This consultation has ended.',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                      fontWeight: FontWeight.bold, color: Colors.grey),
                ),
              ),
            )
          else
            _ChatComposerArea(
              session: session,
              isDark: isDark,
              controller: _messageController,
              onAttach: _handleImageUpload,
              onSend: _sendMessage,
            ),
        ],
      ),
    );
  }
}

class _ChatHeader extends StatelessWidget {
  const _ChatHeader({
    required this.title,
    required this.mdcnNumber,
    required this.session,
    required this.onBack,
    required this.onVoice,
    required this.onVideo,
  });

  final String title;
  final String? mdcnNumber;
  final ConsultationSessionController session;
  final VoidCallback onBack;
  final VoidCallback? onVoice;
  final VoidCallback? onVideo;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;
    final active = session.peerMode != null;
    return SafeArea(
      bottom: false,
      child: Container(
        margin: const EdgeInsets.all(12),
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
        decoration: BoxDecoration(
          color:
              isDark ? Colors.white.withValues(alpha: 0.05) : Colors.grey[200],
          borderRadius: BorderRadius.circular(30),
        ),
        child: Row(
          children: [
            IconButton(
              tooltip: 'Back',
              icon: const Icon(Icons.arrow_back),
              onPressed: onBack,
            ),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                        fontSize: 16, fontWeight: FontWeight.bold),
                  ),
                  if (mdcnNumber?.isNotEmpty == true)
                    Text(
                      'MDCN: $mdcnNumber',
                      style: const TextStyle(
                        fontSize: 12,
                        color: Colors.blue,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  Row(
                    children: [
                      Container(
                        width: 8,
                        height: 8,
                        decoration: BoxDecoration(
                          color: active ? Colors.green : Colors.grey,
                          shape: BoxShape.circle,
                        ),
                      ),
                      const SizedBox(width: 4),
                      Flexible(
                        child: Text(
                          session.peerPresenceLabel,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            fontSize: 12,
                            color: active ? Colors.green : Colors.grey,
                          ),
                        ),
                      ),
                    ],
                  ),
                  if (session.consultationHasStarted ||
                      session.isMessageGracePeriod ||
                      session.isConsultationClosed) ...[
                    const SizedBox(height: 5),
                    ConsultationCountdownBadge(
                      videoEndsAt: session.videoEndsAt,
                      messagesEndAt: session.messagesEndAt,
                      consultationStarted: session.consultationHasStarted,
                      isClosed: session.isConsultationClosed,
                      compact: true,
                    ),
                  ],
                ],
              ),
            ),
            _HeaderCallButton(
              tooltip: 'Voice call',
              icon: Icons.phone_outlined,
              enabled: onVoice != null,
              onPressed: onVoice,
            ),
            _HeaderCallButton(
              tooltip: session.peerMode == ConsultationMode.videoWaiting
                  ? 'Join video'
                  : 'Video call',
              icon: Icons.videocam_outlined,
              enabled: onVideo != null,
              showWaitingDot: session.peerMode == ConsultationMode.videoWaiting,
              onPressed: onVideo,
            ),
          ],
        ),
      ),
    );
  }
}

class _HeaderCallButton extends StatelessWidget {
  const _HeaderCallButton({
    required this.tooltip,
    required this.icon,
    required this.enabled,
    required this.onPressed,
    this.showWaitingDot = false,
  });

  final String tooltip;
  final IconData icon;
  final bool enabled;
  final VoidCallback? onPressed;
  final bool showWaitingDot;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 2),
      decoration: BoxDecoration(
        color: theme.colorScheme.primary.withValues(alpha: 0.1),
        shape: BoxShape.circle,
      ),
      child: Stack(
        clipBehavior: Clip.none,
        children: [
          IconButton(
            tooltip: tooltip,
            icon: Icon(
              icon,
              color: enabled ? theme.colorScheme.primary : Colors.grey,
              size: 20,
            ),
            onPressed: onPressed,
          ),
          if (showWaitingDot)
            const Positioned(
              top: 4,
              right: 4,
              child: DecoratedBox(
                decoration:
                    BoxDecoration(color: Colors.green, shape: BoxShape.circle),
                child: SizedBox(width: 9, height: 9),
              ),
            ),
        ],
      ),
    );
  }
}

class _JoinVideoBanner extends StatelessWidget {
  const _JoinVideoBanner({required this.participant, required this.onJoin});

  final String participant;
  final VoidCallback? onJoin;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      color: colors.primaryContainer,
      child: Row(
        children: [
          const Icon(Icons.video_call_outlined),
          const SizedBox(width: 8),
          Expanded(child: Text('$participant is waiting in video')),
          TextButton.icon(
            onPressed: onJoin,
            icon: const Icon(Icons.videocam),
            label: const Text('Join video'),
          ),
        ],
      ),
    );
  }
}

class _FullChatMessageBubble extends StatelessWidget {
  const _FullChatMessageBubble({
    required this.message,
    required this.myUserId,
    required this.cleanBaseUrl,
    required this.theme,
  });

  final Map<String, dynamic> message;
  final int? myUserId;
  final String cleanBaseUrl;
  final ThemeData theme;

  @override
  Widget build(BuildContext context) {
    final senderId = int.tryParse(message['sender_id'].toString());
    final isMe = senderId == myUserId;
    final content = message['content']?.toString() ?? '';
    final isSending = message['isSending'] == true;
    if (content.contains('"type":"call_signal"')) {
      return const SizedBox.shrink();
    }
    final isImage = content.startsWith('/static/') ||
        content.startsWith('http') ||
        content.startsWith('FILE:');

    return Align(
      alignment: isMe ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.only(bottom: 8),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        constraints:
            BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.75),
        decoration: BoxDecoration(
          color: isMe ? Colors.blueAccent : theme.cardTheme.color,
          borderRadius: BorderRadius.circular(12),
        ),
        child: isImage
            ? GestureDetector(
                onTap: () => _openImage(context, content),
                child: Stack(
                  alignment: Alignment.center,
                  children: [
                    ClipRRect(
                      borderRadius: BorderRadius.circular(8),
                      child: content.startsWith('FILE:')
                          ? Image.file(
                              File(content.substring(5)),
                              height: 200,
                              width: 200,
                              fit: BoxFit.cover,
                            )
                          : Image.network(
                              content.startsWith('http')
                                  ? content
                                  : '$cleanBaseUrl$content',
                              height: 200,
                              width: 200,
                              fit: BoxFit.cover,
                              errorBuilder: (_, __, ___) => const Icon(
                                  Icons.broken_image,
                                  color: Colors.white),
                            ),
                    ),
                    if (isSending)
                      const Positioned.fill(
                        child: ColoredBox(
                          color: Colors.black45,
                          child: Center(
                            child:
                                CircularProgressIndicator(color: Colors.white),
                          ),
                        ),
                      ),
                  ],
                ),
              )
            : Row(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Flexible(
                    child: Text(
                      content,
                      style: TextStyle(
                        color:
                            isMe ? Colors.white : theme.colorScheme.onSurface,
                        fontSize: 16,
                      ),
                    ),
                  ),
                  if (isMe)
                    Padding(
                      padding: const EdgeInsets.only(left: 4),
                      child: isSending
                          ? const SizedBox(
                              width: 12,
                              height: 12,
                              child: CircularProgressIndicator(
                                strokeWidth: 2,
                                color: Colors.white70,
                              ),
                            )
                          : const Icon(Icons.check,
                              size: 14, color: Colors.white70),
                    ),
                ],
              ),
      ),
    );
  }

  void _openImage(BuildContext context, String content) {
    if (content.startsWith('FILE:')) return;
    final url = content.startsWith('http') ? content : '$cleanBaseUrl$content';
    Navigator.push(
      context,
      MaterialPageRoute<void>(
        builder: (_) => Scaffold(
          backgroundColor: Colors.black,
          appBar: AppBar(
            backgroundColor: Colors.black,
            iconTheme: const IconThemeData(color: Colors.white),
          ),
          body: Center(child: InteractiveViewer(child: Image.network(url))),
        ),
      ),
    );
  }
}

class _ChatComposerArea extends StatelessWidget {
  const _ChatComposerArea({
    required this.session,
    required this.isDark,
    required this.controller,
    required this.onAttach,
    required this.onSend,
  });

  final ConsultationSessionController session;
  final bool isDark;
  final TextEditingController controller;
  final VoidCallback onAttach;
  final VoidCallback onSend;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (session.isMessageGracePeriod)
          Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            color: const Color(0xFFF0F7FF),
            child: const Text(
              'Video has ended. Messaging remains open briefly to wrap up.',
              textAlign: TextAlign.center,
              style: TextStyle(
                  color: Color(0xFF1D4ED8), fontWeight: FontWeight.w600),
            ),
          ),
        if (!session.consultationHasStarted && !session.isConsultationClosed)
          Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            color: theme.colorScheme.primary.withValues(alpha: 0.08),
            child: const Text(
              'Waiting for the other participant. Calls unlock when both participants have joined.',
              textAlign: TextAlign.center,
              style: TextStyle(fontWeight: FontWeight.w600),
            ),
          ),
        if (session.connectionState != ConsultationConnectionState.connected)
          Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
            color: theme.colorScheme.errorContainer,
            child: Text(
              session.connectionState ==
                      ConsultationConnectionState.reconnecting
                  ? 'Chat is reconnecting'
                  : 'Chat is temporarily unavailable',
              textAlign: TextAlign.center,
            ),
          ),
        Container(
          padding:
              const EdgeInsets.only(left: 16, right: 16, bottom: 24, top: 12),
          color: theme.colorScheme.surface,
          child: SafeArea(
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 6),
              decoration: BoxDecoration(
                color: isDark
                    ? Colors.white.withValues(alpha: 0.05)
                    : Colors.grey[200],
                borderRadius: BorderRadius.circular(30),
              ),
              child: Row(
                children: [
                  IconButton(
                    tooltip: 'Attach image',
                    icon: Icon(
                      Icons.add_photo_alternate,
                      color: theme.colorScheme.onSurfaceVariant,
                    ),
                    onPressed: onAttach,
                  ),
                  Expanded(
                    child: TextField(
                      controller: controller,
                      minLines: 1,
                      maxLines: 5,
                      keyboardType: TextInputType.multiline,
                      textInputAction: TextInputAction.newline,
                      decoration: const InputDecoration(
                        hintText: 'Type a message...',
                        border: InputBorder.none,
                        contentPadding:
                            EdgeInsets.symmetric(horizontal: 8, vertical: 12),
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  IconButton.filled(
                    tooltip: 'Send message',
                    onPressed: session.canSend ? onSend : null,
                    icon: const Icon(Icons.arrow_upward, size: 20),
                  ),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }
}
