import 'dart:async';
import 'dart:io';
import 'dart:math' as math;

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:just_audio/just_audio.dart';
import 'package:path_provider/path_provider.dart';
import 'package:url_launcher/url_launcher.dart';

import 'package:mediq_app/src/core/api/dio_client.dart';
import 'package:mediq_app/src/core/constants/mdq_ai_assets.dart';
import 'package:mediq_app/src/features/auth/presentation/user_controller.dart';
import 'package:mediq_app/src/features/chat/data/ai_pdf_attachment.dart';
import 'package:mediq_app/src/features/chat/data/image_upload_service.dart';
import 'package:mediq_app/src/features/chat/data/voice_input_capability.dart';
import 'package:mediq_app/src/features/chat/data/voice_input_service.dart';
import 'package:mediq_app/src/features/chat/presentation/ai_chat_controller.dart';
import 'package:mediq_app/src/features/chat/presentation/voice_input_controller.dart';
import 'package:mediq_app/src/features/chat/presentation/widgets/voice_input_microphone_button.dart';
import 'package:mediq_app/src/features/vault/data/vault_repository.dart';
import 'package:go_router/go_router.dart';
import '../../lab/data/lab_result_model.dart';
import 'widgets/lab_result_bubble.dart';
import 'widgets/markdown_bubble.dart';

class AiChatScreen extends ConsumerStatefulWidget {
  final String? sourceSummaryId;
  final String? sourceSummaryUpdatedAt;

  const AiChatScreen({
    super.key,
    this.sourceSummaryId,
    this.sourceSummaryUpdatedAt,
  }) : assert(
          (sourceSummaryId == null) == (sourceSummaryUpdatedAt == null),
          'A continued chat requires both the summary ID and its version.',
        );

  @override
  ConsumerState<AiChatScreen> createState() => _AiChatScreenState();
}

class AiChatExitDialog extends StatelessWidget {
  final bool canSave;
  final VoidCallback onCancel;
  final VoidCallback onExit;
  final Future<void> Function()? onSave;

  const AiChatExitDialog({
    super.key,
    required this.canSave,
    required this.onCancel,
    required this.onExit,
    this.onSave,
  });

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('End Consultation'),
      content: Text(
        canSave
            ? 'This chat is ephemeral — all messages will be discarded when you leave.\n\n'
                'Would you like to save a summary to your Health Vault before exiting?'
            : 'This chat is ephemeral — all messages will be discarded when you leave.',
      ),
      actions: [
        TextButton(
          onPressed: onCancel,
          child: const Text('Cancel'),
        ),
        TextButton(
          style: TextButton.styleFrom(foregroundColor: Colors.redAccent),
          onPressed: onExit,
          child: Text(canSave ? 'Exit & Delete' : 'Exit'),
        ),
        if (canSave)
          FilledButton.icon(
            icon: const Icon(Icons.health_and_safety_outlined, size: 18),
            label: const Text('Exit & Save'),
            onPressed: onSave == null ? null : () async => onSave!(),
          ),
      ],
    );
  }
}

class AiChatWelcomeState extends StatelessWidget {
  const AiChatWelcomeState({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Text(
            "Hello! I'm MDQ+.",
            style: TextStyle(
              color: theme.colorScheme.onSurfaceVariant,
              fontSize: 18,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            'I can help assess your symptoms.',
            style: TextStyle(
              color: theme.colorScheme.onSurfaceVariant.withValues(alpha: 0.7),
              fontSize: 14,
            ),
          ),
          const SizedBox(height: 24),
          Opacity(
            opacity: theme.brightness == Brightness.dark ? 0.16 : 0.20,
            child: Image.asset(
              MdqAiAssets.conversation,
              key: const ValueKey('mdq-ai-conversation'),
              width: 124,
              height: 92,
              fit: BoxFit.contain,
              excludeFromSemantics: true,
            ),
          ),
        ],
      ),
    );
  }
}

class _AiChatScreenState extends ConsumerState<AiChatScreen>
    with WidgetsBindingObserver {
  final TextEditingController _messageController = TextEditingController();
  final ScrollController _scrollController = ScrollController();

  // --- LANGUAGE STATE ---
  String _selectedLanguage = 'English';

  // --- VOICE STATE ---
  late final VoiceInputController _voiceInput;

  // --- TTS STATE ---
  // (Per-message speak — no global auto-play toggle)

  // --- IMAGE STAGING STATE ---
  String? _stagedImageUrl; // Cloudinary URL after upload
  String? _stagedImagePublicId;
  String? _stagedImageFormat;
  bool _isUploadingImage = false;
  AiPdfAttachment? _stagedPdf;
  bool _isPickingPdf = false;
  bool _checkingConsent = true;
  bool _hasAiConsent = false;
  late final AiChatContinuation? _continuation;

  @override
  void initState() {
    super.initState();
    _continuation = widget.sourceSummaryId == null
        ? null
        : AiChatContinuation(
            summaryId: widget.sourceSummaryId!,
            sourceUpdatedAt: widget.sourceSummaryUpdatedAt!,
          );
    WidgetsBinding.instance.addObserver(this);
    _voiceInput = VoiceInputController(
      recorder: RecordVoiceRecorder(),
      transcription: DioVoiceTranscriptionApi(ref.read(dioProvider)),
      tempFiles: VoiceTempFileStore(),
      permission: PermissionHandlerMicrophonePermission(),
    )..addListener(_handleVoiceStateChanged);
    unawaited(_voiceInput.initialize());
    WidgetsBinding.instance.addPostFrameCallback((_) => _initializeAiConsent());
  }

  Future<void> _initializeAiConsent() async {
    try {
      if (_continuation != null) {
        final user = await ref.read(userProvider.future);
        if (user?.isPremium != true) {
          if (!mounted) return;
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text(
                'Continue with AI is available on Premium and Family plans.',
              ),
            ),
          );
          Navigator.of(context).pop();
          return;
        }
      }

      final controller =
          ref.read(aiChatControllerProvider(_continuation).notifier);
      final hasConsent = await controller.hasActiveConsent();
      if (!mounted) return;

      if (hasConsent) {
        setState(() {
          _hasAiConsent = true;
          _checkingConsent = false;
        });
        return;
      }

      final accepted = await _showAiConsentDialog();
      if (!mounted) return;
      if (!accepted) {
        Navigator.of(context).pop();
        return;
      }

      final granted = await controller.grantConsent();
      if (!mounted) return;
      if (!granted) {
        throw StateError('Consent was not recorded.');
      }

      setState(() {
        _hasAiConsent = true;
        _checkingConsent = false;
      });
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Unable to confirm AI consent. Please try again.'),
        ),
      );
      Navigator.of(context).pop();
    }
  }

  Future<bool> _showAiConsentDialog() async {
    final accepted = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Before using MDQ+ AI'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Your symptoms, health text, chronic conditions, and uploaded '
                'images or PDF documents may be processed by our third-party AI provider.',
              ),
              const SizedBox(height: 12),
              const Text(
                'MDQ+ AI provides health information and preliminary guidance. '
                'It is not a confirmed diagnosis, prescription, or emergency service.',
              ),
              const SizedBox(height: 12),
              Wrap(
                spacing: 8,
                children: [
                  TextButton(
                    onPressed: () => launchUrl(
                      Uri.parse('https://mdqplus.com/legal.html#privacy'),
                      mode: LaunchMode.externalApplication,
                    ),
                    child: const Text('Privacy Policy'),
                  ),
                  TextButton(
                    onPressed: () => launchUrl(
                      Uri.parse('https://mdqplus.com/legal.html#terms'),
                      mode: LaunchMode.externalApplication,
                    ),
                    child: const Text('Terms'),
                  ),
                ],
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text('I understand and continue'),
          ),
        ],
      ),
    );
    return accepted == true;
  }

  void _handleVoiceStateChanged() {
    if (!mounted) return;
    final transcript = _voiceInput.consumeTranscript();
    setState(() {
      if (transcript != null) {
        _messageController.text = transcript;
        _messageController.selection = TextSelection.collapsed(
          offset: transcript.length,
        );
      }
    });
  }

  Future<void> _toggleVoiceInput() async {
    final voiceState = _voiceInput.state;
    if (voiceState.phase == VoiceInputPhase.recording) {
      await _voiceInput.stopAndTranscribe();
      return;
    }
    if (voiceState.phase != VoiceInputPhase.idle) return;

    final capability = aiLanguageCapabilityFor(_selectedLanguage);
    if (!capability.voiceInputEnabled) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            "Voice input isn't available for $_selectedLanguage yet. "
            'You can still type your message.',
          ),
        ),
      );
      return;
    }

    final outcome = await _voiceInput.start(
      language: _selectedLanguage,
      existingComposerText: _messageController.text,
    );
    if (!mounted) return;
    if (outcome == VoiceStartOutcome.permissionDenied) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Microphone permission is required for voice input.'),
        ),
      );
    } else if (outcome == VoiceStartOutcome.permissionPermanentlyDenied) {
      await showDialog<void>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          title: const Text('Microphone permission required'),
          content: const Text(
            'Allow microphone access in app settings to use voice input.',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(dialogContext).pop(),
              child: const Text('Not now'),
            ),
            FilledButton(
              onPressed: () {
                Navigator.of(dialogContext).pop();
                unawaited(_voiceInput.openPermissionSettings());
              },
              child: const Text('Open settings'),
            ),
          ],
        ),
      );
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.inactive &&
        _voiceInput.isRequestingMicrophonePermission) {
      return;
    }
    if (state != AppLifecycleState.resumed) {
      unawaited(_voiceInput.interrupt());
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _voiceInput.removeListener(_handleVoiceStateChanged);
    unawaited(_voiceInput.disposeAsync());
    _messageController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  void _scrollToBottom() {
    if (_scrollController.hasClients) {
      Future.delayed(const Duration(milliseconds: 100), () {
        if (_scrollController.hasClients) {
          final position = _scrollController.position;
          if (position.maxScrollExtent - position.pixels <= 100) {
            _scrollController.animateTo(
              position.maxScrollExtent,
              duration: const Duration(milliseconds: 300),
              curve: Curves.easeOut,
            );
          }
        }
      });
    }
  }

  /// Stage an image: pick → upload → store URL for preview
  Future<void> _stageImage() async {
    await _deleteStagedImage();
    if (!mounted) return;
    setState(() {
      _stagedPdf = null;
      _isUploadingImage = true;
    });
    try {
      final image = await ref
          .read(imageUploadServiceProvider)
          .pickAndUploadTemporaryAiImage();
      if (image != null && mounted) {
        setState(() {
          _stagedImageUrl = image.url;
          _stagedImagePublicId = image.publicId;
          _stagedImageFormat = image.format;
        });
      }
    } catch (_) {
      debugPrint('[AiChatScreen] image staging failed.');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Image upload is unavailable. Please try again.'),
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _isUploadingImage = false);
    }
  }

  Future<void> _deleteStagedImage() async {
    final publicId = _stagedImagePublicId;
    if (mounted) {
      setState(() {
        _stagedImageUrl = null;
        _stagedImagePublicId = null;
        _stagedImageFormat = null;
      });
    }
    if (publicId != null) {
      await ref
          .read(aiChatControllerProvider(_continuation).notifier)
          .deleteTemporaryImage(publicId);
    }
  }

  Future<void> _stagePdf() async {
    await _deleteStagedImage();
    if (!mounted) return;
    setState(() => _isPickingPdf = true);
    try {
      final document = await ref.read(aiPdfPickerProvider).pick();
      if (document != null && mounted) {
        setState(() => _stagedPdf = document);
      }
    } on AiPdfSelectionException catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(e.message)),
        );
      }
    } catch (_) {
      debugPrint('[AiChatScreen] PDF selection failed.');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('This PDF could not be selected. Please try again.'),
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _isPickingPdf = false);
    }
  }

  void _removeStagedPdf() {
    setState(() => _stagedPdf = null);
  }

  /// Send message with optional staged image
  void _sendMessage() {
    final chatState = ref.read(aiChatControllerProvider(_continuation));
    if (chatState.isLoading ||
        _isUploadingImage ||
        _isPickingPdf ||
        _voiceInput.state.locksComposer) {
      return;
    }

    final text = _messageController.text.trim();
    final imageUrl = _stagedImageUrl;
    final imagePublicId = _stagedImagePublicId;
    final imageFormat = _stagedImageFormat;
    final document = _stagedPdf;

    // Need either text or an image
    if (text.isEmpty && imageUrl == null && document == null) return;

    final messageText = text.isNotEmpty
        ? text
        : document != null
            ? 'Analyse and explain this PDF document.'
            : 'Analyze this image';

    ref.read(aiChatControllerProvider(_continuation).notifier).sendMessage(
        messageText,
        imageUrl: imageUrl,
        imagePublicId: imagePublicId,
        imageFormat: imageFormat,
        document: document,
        language: _selectedLanguage);

    _messageController.clear();
    setState(() {
      _stagedImageUrl = null;
      _stagedImagePublicId = null;
      _stagedImageFormat = null;
      _stagedPdf = null;
    });

    // Scroll after state update
    WidgetsBinding.instance.addPostFrameCallback((_) => _scrollToBottom());
  }

  Future<void> _showAttachmentMenu() async {
    showModalBottomSheet(
      context: context,
      builder: (context) => SafeArea(
        child: Wrap(
          children: [
            ListTile(
              leading: const Icon(Icons.science, color: Colors.blueAccent),
              title: const Text('Scan Urine Test Strip'),
              subtitle: const Text('Analyze urinalysis strip with AI'),
              onTap: () async {
                Navigator.pop(context); // Close menu

                final user = ref.read(userProvider).value;
                if (user?.isPremium != true) {
                  // SHOW PAYWALL DIALOG
                  showDialog(
                    context: context,
                    builder: (BuildContext dialogContext) => const AlertDialog(
                      title: Row(
                        children: [
                          Icon(Icons.star, color: Colors.amber),
                          SizedBox(width: 8),
                          Text("MDQ+ Premium Required",
                              style: TextStyle(fontSize: 18)),
                        ],
                      ),
                      content: Text(
                          "AI Urinalysis is exclusively available for MDQ+ Premium subscribers. Upgrade your plan to unlock this and other advanced medical analysis features."),
                    ),
                  );
                  return;
                }

                // Premium User -> Proceed to scanner
                final result =
                    await context.push<LabAnalysisResponse>('/lab_scanner');
                if (result != null) {
                  ref
                      .read(aiChatControllerProvider(_continuation).notifier)
                      .sendLabResult(result);
                  WidgetsBinding.instance
                      .addPostFrameCallback((_) => _scrollToBottom());
                }
              },
            ),
            ListTile(
              leading: const Icon(Icons.image, color: Colors.orangeAccent),
              title: const Text('Upload Photo'),
              subtitle: const Text('Skin issues, wounds, etc.'),
              onTap: () {
                Navigator.pop(context);
                _stageImage(); // Stage, don't send immediately
              },
            ),
            ListTile(
              leading:
                  const Icon(Icons.picture_as_pdf, color: Colors.redAccent),
              title: const Text('Upload PDF'),
              subtitle: const Text('Medical reports and other documents'),
              onTap: () {
                Navigator.pop(context);
                _stagePdf();
              },
            ),
          ],
        ),
      ),
    );
  }

  /// Ends Free chats directly and offers paid users the existing save choice.
  Future<void> _showExitDialog() async {
    await _voiceInput.interrupt();
    if (!mounted) return;
    final controller =
        ref.read(aiChatControllerProvider(_continuation).notifier);
    final canSave = controller.hasPaidContinuity;
    final shouldClose = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) => AiChatExitDialog(
        canSave: canSave,
        onCancel: () => Navigator.of(dialogContext).pop(false),
        onExit: () => Navigator.of(dialogContext).pop(true),
        onSave: !canSave
            ? null
            : () async {
                Navigator.of(dialogContext)
                    .pop(false); // keep screen alive for now
                await _deleteStagedImage();
                if (!mounted) return;
                final success = await ref
                    .read(aiChatControllerProvider(_continuation).notifier)
                    .saveSummary();
                if (!mounted) return;
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(
                    content: Text(
                      success
                          ? '✅ Summary saved to Health Vault!'
                          : 'Couldn’t save this chat. Please try again.',
                    ),
                    duration: const Duration(seconds: 2),
                  ),
                );
                if (success && mounted) {
                  ref.invalidate(vaultHistoryProvider);
                  Navigator.of(context).pop();
                }
              },
      ),
    );

    if (shouldClose == true && mounted) {
      await _deleteStagedImage();
      if (!mounted) return;
      setState(() => _stagedPdf = null);
      Navigator.of(context).pop();
    }
  }

  String _formatVoiceDuration(Duration duration) {
    final seconds = duration.inSeconds.clamp(0, 90);
    return '${(seconds ~/ 60).toString().padLeft(2, '0')}:'
        '${(seconds % 60).toString().padLeft(2, '0')}';
  }

  Widget _buildVoiceInputStatus(
    ThemeData theme,
    VoiceInputState voiceState,
  ) {
    final elapsed = _formatVoiceDuration(voiceState.elapsed);
    final remaining = 90 - voiceState.elapsed.inSeconds.clamp(0, 90);

    late final Widget leading;
    late final String label;
    switch (voiceState.phase) {
      case VoiceInputPhase.starting:
        leading = const SizedBox.square(
          dimension: 18,
          child: CircularProgressIndicator(strokeWidth: 2),
        );
        label = 'Starting microphone…';
        break;
      case VoiceInputPhase.recording:
        leading = const Icon(Icons.fiber_manual_record,
            color: Colors.redAccent, size: 18);
        label =
            'Recording $elapsed${remaining <= 10 ? ' • ${remaining}s left' : ''}';
        break;
      case VoiceInputPhase.stopping:
        leading = const SizedBox.square(
          dimension: 18,
          child: CircularProgressIndicator(strokeWidth: 2),
        );
        label = 'Finishing recording…';
        break;
      case VoiceInputPhase.transcribing:
        leading = const SizedBox.square(
          dimension: 18,
          child: CircularProgressIndicator(strokeWidth: 2),
        );
        label = 'Transcribing $elapsed recording…';
        break;
      case VoiceInputPhase.error:
        leading =
            Icon(Icons.info_outline, color: theme.colorScheme.error, size: 18);
        label =
            voiceState.errorMessage ?? 'Voice input could not be completed.';
        break;
      case VoiceInputPhase.idle:
      case VoiceInputPhase.ready:
        return const SizedBox.shrink();
    }

    return Container(
      width: double.infinity,
      margin: const EdgeInsets.fromLTRB(16, 8, 16, 0),
      padding: const EdgeInsets.fromLTRB(12, 8, 8, 8),
      decoration: BoxDecoration(
        color: theme.colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(14),
      ),
      child: Row(
        children: [
          leading,
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              label,
              style: theme.textTheme.bodySmall,
            ),
          ),
          if (voiceState.phase == VoiceInputPhase.recording)
            TextButton(
              onPressed: _voiceInput.stopAndTranscribe,
              child: const Text('Stop'),
            ),
          if (voiceState.phase == VoiceInputPhase.error && voiceState.canRetry)
            TextButton(
              onPressed: _voiceInput.retry,
              child: const Text('Retry'),
            ),
          TextButton(
            onPressed: _voiceInput.cancel,
            child: const Text('Cancel'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final chatState = ref.watch(aiChatControllerProvider(_continuation));
    final userAsync = ref.watch(userProvider);
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;
    final voiceState = _voiceInput.state;

    // Scroll to bottom when messages change
    WidgetsBinding.instance.addPostFrameCallback((_) => _scrollToBottom());

    return PopScope(
      canPop: false, // Prevent immediate close
      onPopInvokedWithResult: (didPop, _) async {
        if (didPop) return;
        _showExitDialog();
      },
      child: Scaffold(
        backgroundColor: theme.colorScheme.surface,
        appBar: AppBar(
          title: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text("MDQ+",
                  style: TextStyle(
                      color: theme.colorScheme.onSurface,
                      fontSize: 18,
                      fontWeight: FontWeight.w600)),
              userAsync.when(
                data: (user) => Text(
                  user?.isPremium == true ? "Premium Mode ⚡" : "Free Mode",
                  style: const TextStyle(
                      fontSize: 10,
                      color: Colors.greenAccent,
                      fontWeight: FontWeight.w500,
                      letterSpacing: 0.5),
                ),
                loading: () => Text("Connecting...",
                    style: TextStyle(
                        fontSize: 10,
                        color: theme.colorScheme.onSurfaceVariant)),
                error: (_, __) => const SizedBox.shrink(),
              ),
            ],
          ),
          backgroundColor:
              isDark ? theme.colorScheme.surface : Colors.grey.shade50,
          foregroundColor: theme.colorScheme.onSurface,
          elevation: 2,
          shadowColor: Colors.black.withValues(alpha: 0.1),
          surfaceTintColor: Colors.transparent,
          actions: [
            PopupMenuButton<String>(
              enabled: !voiceState.locksLanguage,
              icon: Icon(Icons.language, color: theme.colorScheme.onSurface),
              onSelected: (String lang) {
                setState(() => _selectedLanguage = lang);
              },
              color: theme.colorScheme.surface,
              shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12)),
              elevation: 4,
              itemBuilder: (BuildContext context) {
                return aiLanguageCapabilities.keys.map((String choice) {
                  return PopupMenuItem<String>(
                    value: choice,
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Text(choice,
                            style: TextStyle(
                                color: _selectedLanguage == choice
                                    ? Colors.blue
                                    : theme.colorScheme.onSurface)),
                        if (_selectedLanguage == choice)
                          const Icon(Icons.check, color: Colors.blue, size: 20),
                      ],
                    ),
                  );
                }).toList();
              },
            ),
          ],
        ),
        body: Column(
          children: [
            Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 7),
              color: theme.colorScheme.primaryContainer.withValues(alpha: 0.45),
              child: Text(
                'AI support only - not a confirmed diagnosis.',
                textAlign: TextAlign.center,
                style: TextStyle(
                  color: theme.colorScheme.onPrimaryContainer,
                  fontSize: 12,
                  fontWeight: FontWeight.w500,
                ),
              ),
            ),
            if (widget.sourceSummaryId != null)
              Container(
                width: double.infinity,
                padding:
                    const EdgeInsets.symmetric(horizontal: 16, vertical: 9),
                color: Colors.amber.withValues(alpha: 0.16),
                child: Text(
                  'Continuing from a saved AI summary. Earlier information may be out of date; tell MDQ+ what has changed.',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: isDark ? Colors.amber[200] : Colors.brown[700],
                    fontSize: 12,
                    fontWeight: FontWeight.w500,
                  ),
                ),
              ),
            Expanded(
              child: _checkingConsent || !_hasAiConsent
                  ? const Center(child: CircularProgressIndicator())
                  : chatState.messages.isEmpty
                      ? const AiChatWelcomeState()
                      : ListView.builder(
                          controller: _scrollController,
                          padding: const EdgeInsets.all(16),
                          itemCount: chatState.messages.length,
                          itemBuilder: (context, index) {
                            final msg = chatState.messages[index];
                            final isMe = msg['role'] == 'user';

                            if (msg['type'] == 'usage_notice') {
                              return Container(
                                margin: const EdgeInsets.symmetric(vertical: 8),
                                padding: const EdgeInsets.all(12),
                                decoration: BoxDecoration(
                                  color: theme.colorScheme.secondaryContainer,
                                  borderRadius: BorderRadius.circular(12),
                                ),
                                child: Text(
                                  msg['message'] as String,
                                  textAlign: TextAlign.center,
                                  style: TextStyle(
                                    color:
                                        theme.colorScheme.onSecondaryContainer,
                                    fontSize: 12,
                                  ),
                                ),
                              );
                            }

                            // 1. Check for Lab Result Message
                            if (msg['type'] == 'lab_result' &&
                                msg['lab_data'] != null) {
                              return LabResultBubble(
                                result: msg['lab_data'] as LabAnalysisResponse,
                                isMe: isMe,
                              );
                            }

                            return _buildMessageBubble(
                              msg['message'],
                              isMe,
                              imageUrl: msg['image'],
                              documentName: msg['documentName'],
                              isSending: msg['isSending'] == true,
                              theme: theme,
                              isDark: isDark,
                            );
                          },
                        ),
            ),
            if (chatState.isLoading)
              Padding(
                padding: const EdgeInsets.all(8.0),
                child: Text("MDQ+ is analyzing...",
                    style: TextStyle(color: theme.hintColor)),
              ),

            // --- STAGED IMAGE PREVIEW ---
            if (_stagedImageUrl != null)
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                color: isDark ? Colors.grey[900] : Colors.grey[100],
                child: Row(
                  children: [
                    ClipRRect(
                      borderRadius: BorderRadius.circular(8),
                      child: Image.network(
                        _stagedImageUrl!,
                        width: 60,
                        height: 60,
                        fit: BoxFit.cover,
                        errorBuilder: (c, e, s) => Container(
                          width: 60,
                          height: 60,
                          color: Colors.grey[300],
                          child: const Icon(Icons.broken_image, size: 24),
                        ),
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        "Image attached",
                        style: TextStyle(
                          color: isDark ? Colors.grey[400] : Colors.grey[600],
                          fontSize: 13,
                        ),
                      ),
                    ),
                    IconButton(
                      icon: const Icon(Icons.close, size: 20),
                      onPressed: () => _deleteStagedImage(),
                      color: Colors.redAccent,
                      tooltip: "Remove image",
                    ),
                  ],
                ),
              ),

            if (_stagedPdf != null)
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                color: isDark ? Colors.grey[900] : Colors.grey[100],
                child: Row(
                  children: [
                    const Icon(Icons.picture_as_pdf,
                        color: Colors.redAccent, size: 32),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        _stagedPdf!.name,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          color: isDark ? Colors.grey[300] : Colors.grey[700],
                          fontSize: 13,
                        ),
                      ),
                    ),
                    IconButton(
                      icon: const Icon(Icons.close, size: 20),
                      onPressed: _removeStagedPdf,
                      color: Colors.redAccent,
                      tooltip: 'Remove PDF',
                    ),
                  ],
                ),
              ),

            // --- UPLOADING INDICATOR ---
            if (_isUploadingImage)
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                color: isDark ? Colors.grey[900] : Colors.grey[100],
                child: Row(
                  children: [
                    const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    ),
                    const SizedBox(width: 10),
                    Text("Uploading image...",
                        style: TextStyle(color: theme.hintColor, fontSize: 13)),
                  ],
                ),
              ),

            if (voiceState.phase != VoiceInputPhase.idle)
              _buildVoiceInputStatus(theme, voiceState),

            // --- INPUT BAR ---
            Container(
              padding: const EdgeInsets.only(
                  left: 16, right: 16, bottom: 24, top: 12),
              color: theme.colorScheme.surface,
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 6),
                decoration: BoxDecoration(
                  color: isDark
                      ? Colors.white.withValues(alpha: 0.1)
                      : Colors.grey[100],
                  borderRadius: BorderRadius.circular(30),
                  border: Border.all(
                      color: isDark
                          ? Colors.white.withValues(alpha: 0.05)
                          : Colors.transparent),
                ),
                child: Row(
                  children: [
                    IconButton(
                      icon: const Icon(Icons.add_circle,
                          color: Colors.blueAccent),
                      onPressed: _hasAiConsent &&
                              !chatState.isLoading &&
                              !_isUploadingImage &&
                              !_isPickingPdf &&
                              !voiceState.locksComposer
                          ? _showAttachmentMenu
                          : null,
                    ),
                    Expanded(
                      child: TextField(
                        controller: _messageController,
                        enabled: _hasAiConsent &&
                            !chatState.isLoading &&
                            !_isUploadingImage &&
                            !_isPickingPdf &&
                            !voiceState.locksComposer,
                        style: TextStyle(
                            color: isDark ? Colors.white : Colors.black87),
                        minLines: 1,
                        maxLines: 5,
                        keyboardType: TextInputType.multiline,
                        textInputAction: TextInputAction.newline,
                        decoration: InputDecoration(
                          hintText: voiceState.phase ==
                                  VoiceInputPhase.recording
                              ? "Recording..."
                              : voiceState.phase == VoiceInputPhase.transcribing
                                  ? 'Transcribing...'
                                  : (_stagedImageUrl != null ||
                                          _stagedPdf != null
                                      ? "Add a message..."
                                      : "Describe symptoms..."),
                          hintStyle: TextStyle(
                              color: voiceState.phase ==
                                      VoiceInputPhase.recording
                                  ? Colors.redAccent
                                  : (isDark ? Colors.white54 : Colors.black54),
                              fontSize: 15),
                          border: InputBorder.none,
                          contentPadding: const EdgeInsets.symmetric(
                              horizontal: 8, vertical: 12),
                        ),
                      ),
                    ),
                    VoiceInputMicrophoneButton(
                      selectedLanguage: _selectedLanguage,
                      phase: voiceState.phase,
                      interactionEnabled: _hasAiConsent &&
                          !chatState.isLoading &&
                          !_isUploadingImage &&
                          !_isPickingPdf &&
                          (voiceState.phase == VoiceInputPhase.idle ||
                              voiceState.phase == VoiceInputPhase.recording),
                      onPressed: _toggleVoiceInput,
                    ),
                    const SizedBox(width: 4),
                    Container(
                      decoration: const BoxDecoration(
                        color: Color(0xFF4A90E2),
                        shape: BoxShape.circle,
                      ),
                      child: IconButton(
                        onPressed: _hasAiConsent &&
                                !chatState.isLoading &&
                                !_isUploadingImage &&
                                !_isPickingPdf &&
                                !voiceState.locksComposer
                            ? _sendMessage
                            : null,
                        icon: const Icon(Icons.arrow_upward,
                            color: Colors.white, size: 20),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildMessageBubble(String text, bool isMe,
      {String? imageUrl,
      String? documentName,
      bool isSending = false,
      required ThemeData theme,
      required bool isDark}) {
    // Resolve the image URL: if it's already a full URL, use it directly
    String? resolvedImageUrl;
    if (imageUrl != null) {
      if (imageUrl.startsWith('http://') || imageUrl.startsWith('https://')) {
        resolvedImageUrl = imageUrl;
      } else {
        // Legacy: relative path — prepend backend base URL
        final baseUrl = ref.read(dioProvider).options.baseUrl;
        final cleanBaseUrl = baseUrl.endsWith('/')
            ? baseUrl.substring(0, baseUrl.length - 1)
            : baseUrl;
        resolvedImageUrl = "$cleanBaseUrl$imageUrl";
      }
    }

    return Align(
      alignment: isMe ? Alignment.centerRight : Alignment.centerLeft,
      child: Column(
        crossAxisAlignment:
            isMe ? CrossAxisAlignment.end : CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            margin: const EdgeInsets.symmetric(vertical: 4),
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
            constraints: BoxConstraints(
              maxWidth: MediaQuery.of(context).size.width * 0.8,
            ),
            decoration: BoxDecoration(
              color: isMe
                  ? Colors.blue
                  : (isDark ? const Color(0xFF2C2C2C) : Colors.grey[200]),
              borderRadius: BorderRadius.only(
                topLeft: const Radius.circular(16),
                topRight: const Radius.circular(16),
                bottomLeft: isMe ? const Radius.circular(16) : Radius.zero,
                bottomRight: isMe ? Radius.zero : const Radius.circular(16),
              ),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (documentName != null)
                  Container(
                    margin: const EdgeInsets.only(bottom: 8),
                    padding:
                        const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                    decoration: BoxDecoration(
                      color: isMe
                          ? Colors.white24
                          : Colors.red.withValues(alpha: 0.08),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.picture_as_pdf,
                            size: 18,
                            color: isMe ? Colors.white : Colors.redAccent),
                        const SizedBox(width: 7),
                        Flexible(
                          child: Text(
                            documentName,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                              color: isMe
                                  ? Colors.white
                                  : theme.colorScheme.onSurface,
                              fontSize: 12,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                if (resolvedImageUrl != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 8.0),
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(10),
                      child: ConstrainedBox(
                        constraints: const BoxConstraints(maxHeight: 200),
                        child: Image.network(
                          resolvedImageUrl,
                          width: double.infinity,
                          fit: BoxFit.cover,
                          loadingBuilder: (context, child, loadingProgress) {
                            if (loadingProgress == null) return child;
                            return Container(
                              height: 120,
                              color: Colors.grey[300],
                              child: const Center(
                                child:
                                    CircularProgressIndicator(strokeWidth: 2),
                              ),
                            );
                          },
                          errorBuilder: (c, e, s) => Container(
                            height: 120,
                            color: Colors.grey[300],
                            child: const Center(
                              child: Icon(Icons.broken_image,
                                  color: Colors.grey, size: 32),
                            ),
                          ),
                        ),
                      ),
                    ),
                  ),
                MarkdownBubble(
                  data: text,
                  isMe: isMe,
                  isDark: isDark,
                ),
                if (isMe)
                  Align(
                    alignment: Alignment.bottomRight,
                    child: Padding(
                      padding: const EdgeInsets.only(top: 4.0),
                      child: isSending
                          ? const SizedBox(
                              width: 12,
                              height: 12,
                              child: CircularProgressIndicator(
                                  strokeWidth: 2, color: Colors.white70),
                            )
                          : const Icon(Icons.check,
                              size: 14, color: Colors.white70),
                    ),
                  ),
              ],
            ),
          ),
          // ── Per-message TTS button (AI messages only) ────────────────────
          if (!isMe)
            Padding(
              padding: const EdgeInsets.only(left: 4, bottom: 2),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  _PremiumVoiceButton(
                    text: text,
                    language: _selectedLanguage,
                    isDark: isDark,
                  ),
                  _FlagButton(
                    messageText: text,
                    onReport: _showReportDialog,
                    isDark: isDark,
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }

  // ── Report AI Response dialog ─────────────────────────────────────────────
  Future<void> _showReportDialog(String messageText) async {
    String? selectedReason;
    bool isSubmitting = false;

    await showDialog<void>(
      context: context,
      barrierDismissible: !isSubmitting,
      builder: (dialogContext) {
        return StatefulBuilder(
          builder: (context, setDialogState) {
            return AlertDialog(
              title: const Row(
                children: [
                  Icon(Icons.flag_outlined, size: 20, color: Colors.orange),
                  SizedBox(width: 8),
                  Text('Report AI Response'),
                ],
              ),
              content: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'Please select the reason for reporting this response:',
                    style: TextStyle(fontSize: 13),
                  ),
                  const SizedBox(height: 16),
                  DropdownButtonFormField<String>(
                    initialValue: selectedReason,
                    decoration: InputDecoration(
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(8),
                      ),
                      contentPadding: const EdgeInsets.symmetric(
                        horizontal: 12,
                        vertical: 10,
                      ),
                      isDense: true,
                    ),
                    hint: const Text('Select a reason'),
                    items: const [
                      DropdownMenuItem(
                        value: 'Inaccurate medical information',
                        child: Text('Inaccurate medical information'),
                      ),
                      DropdownMenuItem(
                        value: 'Inappropriate content',
                        child: Text('Inappropriate content'),
                      ),
                      DropdownMenuItem(
                        value: 'Other',
                        child: Text('Other'),
                      ),
                    ],
                    onChanged: isSubmitting
                        ? null
                        : (value) {
                            setDialogState(() => selectedReason = value);
                          },
                  ),
                ],
              ),
              actions: [
                TextButton(
                  onPressed: isSubmitting
                      ? null
                      : () => Navigator.of(dialogContext).pop(),
                  child: const Text('Cancel'),
                ),
                FilledButton(
                  onPressed: (selectedReason == null || isSubmitting)
                      ? null
                      : () async {
                          setDialogState(() => isSubmitting = true);
                          // Capture messenger before async gap to avoid
                          // use_build_context_synchronously lint warnings.
                          final messenger = ScaffoldMessenger.of(dialogContext);
                          try {
                            await ref
                                .read(aiChatControllerProvider(_continuation)
                                    .notifier)
                                .reportMessage(messageText, selectedReason!);
                            if (dialogContext.mounted) {
                              Navigator.of(dialogContext).pop();
                            }
                            messenger.showSnackBar(
                              const SnackBar(
                                content: Text(
                                  '\u2705 Report submitted. Thank you for your feedback.',
                                ),
                                duration: Duration(seconds: 3),
                              ),
                            );
                          } catch (_) {
                            setDialogState(() => isSubmitting = false);
                            messenger.showSnackBar(
                              const SnackBar(
                                content: Text(
                                  'Failed to submit report. Please try again.',
                                ),
                              ),
                            );
                          }
                        },
                  child: isSubmitting
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.white,
                          ),
                        )
                      : const Text('Submit'),
                ),
              ],
            );
          },
        );
      },
    );
  }
}

enum _VoiceState { idle, loading, playing }

class _PremiumVoiceButton extends ConsumerStatefulWidget {
  final String text;
  final String language;
  final bool isDark;

  const _PremiumVoiceButton({
    required this.text,
    required this.language,
    required this.isDark,
  });

  @override
  ConsumerState<_PremiumVoiceButton> createState() =>
      _PremiumVoiceButtonState();
}

class _PremiumVoiceButtonState extends ConsumerState<_PremiumVoiceButton> {
  _VoiceState _state = _VoiceState.idle;
  late AudioPlayer _player;

  @override
  void initState() {
    super.initState();
    _player = AudioPlayer();
    _player.playerStateStream.listen((state) {
      if (state.processingState == ProcessingState.completed) {
        if (mounted) setState(() => _state = _VoiceState.idle);
      }
    });
  }

  @override
  void dispose() {
    _player.dispose();
    super.dispose();
  }

  Future<void> _handleTap() async {
    if (_state == _VoiceState.playing) {
      await _player.stop();
      if (mounted) setState(() => _state = _VoiceState.idle);
      return;
    }

    if (mounted) setState(() => _state = _VoiceState.loading);

    try {
      final dio = ref.read(dioProvider);

      final cleanText = widget.text
          .replaceAll(RegExp(r'[*_`#>~]'), '')
          .replaceAll(RegExp(r'\n+'), '. ')
          .trim();

      final dir = await getTemporaryDirectory();
      final languageKey = widget.language
          .trim()
          .toLowerCase()
          .replaceAll(RegExp(r'[^a-z0-9]+'), '_');
      final file = File(
          '${dir.path}/temp_voice_${languageKey}_${cleanText.hashCode}.mp3');

      if (file.existsSync()) {
        await _player.setFilePath(file.path);
        if (mounted) setState(() => _state = _VoiceState.playing);
        _player.play();
        return;
      }

      final response = await dio.post(
        '/api/v1/voice/speak',
        data: {
          'text': cleanText,
          'language': widget.language,
        },
        options: Options(responseType: ResponseType.bytes),
      );

      await file.writeAsBytes(response.data as List<int>);

      await _player.setFilePath(file.path);
      if (mounted) setState(() => _state = _VoiceState.playing);
      _player.play();
    } catch (_) {
      debugPrint('[VOICE] playback request failed.');
      if (mounted) {
        setState(() => _state = _VoiceState.idle);
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Voice playback is unavailable. Please try again.'),
          ),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_state == _VoiceState.loading) {
      return Padding(
        padding: const EdgeInsets.only(left: 10, bottom: 4, top: 4, right: 10),
        child: SizedBox(
          width: 24,
          height: 12,
          child: _BouncingDots(isDark: widget.isDark),
        ),
      );
    }

    return IconButton(
      tooltip: _state == _VoiceState.playing ? 'Stop' : 'Read aloud',
      padding: EdgeInsets.zero,
      constraints: const BoxConstraints(minWidth: 28, minHeight: 28),
      icon: Icon(
        _state == _VoiceState.playing
            ? Icons.stop_circle_outlined
            : Icons.volume_up_outlined,
        size: 16,
        color: widget.isDark ? Colors.white30 : Colors.black26,
      ),
      onPressed: _handleTap,
    );
  }
}

class _BouncingDots extends StatefulWidget {
  final bool isDark;
  const _BouncingDots({required this.isDark});

  @override
  State<_BouncingDots> createState() => _BouncingDotsState();
}

class _BouncingDotsState extends State<_BouncingDots>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    )..repeat();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Widget _buildDot(int index) {
    return AnimatedBuilder(
      animation: _controller,
      builder: (context, child) {
        final double phase = (_controller.value * 2 * math.pi) - (index * 1.0);
        final double y = math.sin(phase) * 3;

        return Transform.translate(
          offset: Offset(0, y),
          child: Container(
            margin: const EdgeInsets.symmetric(horizontal: 2),
            width: 4,
            height: 4,
            decoration: BoxDecoration(
              color: widget.isDark ? Colors.white54 : Colors.black54,
              shape: BoxShape.circle,
            ),
          ),
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        _buildDot(0),
        _buildDot(1),
        _buildDot(2),
      ],
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// _FlagButton — small flag icon shown below AI message bubbles only.
// Tapping it triggers the "Report AI Response" dialog on the parent state.
// ─────────────────────────────────────────────────────────────────────────────
class _FlagButton extends StatelessWidget {
  final String messageText;
  final Future<void> Function(String) onReport;
  final bool isDark;

  const _FlagButton({
    required this.messageText,
    required this.onReport,
    required this.isDark,
  });

  @override
  Widget build(BuildContext context) {
    return IconButton(
      tooltip: 'Report this response',
      padding: EdgeInsets.zero,
      constraints: const BoxConstraints(minWidth: 28, minHeight: 28),
      icon: Icon(
        Icons.flag_outlined,
        size: 16,
        color: isDark ? Colors.white30 : Colors.black26,
      ),
      onPressed: () => onReport(messageText),
    );
  }
}
