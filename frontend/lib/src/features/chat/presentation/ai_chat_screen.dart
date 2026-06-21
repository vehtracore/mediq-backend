import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:speech_to_text/speech_to_text.dart' as stt;
import 'package:permission_handler/permission_handler.dart';
import 'dart:io';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:just_audio/just_audio.dart';
import 'package:path_provider/path_provider.dart';
import 'package:dio/dio.dart';
import 'dart:math' as math;
import 'package:mediq_app/src/features/chat/presentation/ai_chat_controller.dart';
import 'package:mediq_app/src/features/auth/presentation/user_controller.dart';
import 'package:mediq_app/src/features/chat/data/image_upload_service.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';
import '../../lab/data/lab_result_model.dart';
import 'widgets/lab_result_bubble.dart';
import 'widgets/markdown_bubble.dart';

class AiChatScreen extends ConsumerStatefulWidget {
  const AiChatScreen({super.key});

  @override
  ConsumerState<AiChatScreen> createState() => _AiChatScreenState();
}

class _AiChatScreenState extends ConsumerState<AiChatScreen> {
  final TextEditingController _messageController = TextEditingController();
  final ScrollController _scrollController = ScrollController();

  // --- LANGUAGE STATE ---
  String _selectedLanguage = 'English';

  // --- VOICE STATE ---
  late stt.SpeechToText _speech;
  bool _isListening = false; // Visual UI state (drives the pulsing mic)
  bool _isUserIntendingToListen = false; // Master toggle — survives OS kills
  bool _speechEnabled = false;
  String _preListenText =
      ''; // Accumulated text snapshot before each listen cycle

  // --- TTS STATE ---
  // (Per-message speak — no global auto-play toggle)

  // --- IMAGE STAGING STATE ---
  String? _stagedImageUrl; // Cloudinary URL after upload
  String? _stagedImagePublicId;
  bool _isUploadingImage = false;
  bool _checkingConsent = true;
  bool _hasAiConsent = false;

  @override
  void initState() {
    super.initState();
    _speech = stt.SpeechToText();
    WidgetsBinding.instance.addPostFrameCallback((_) => _initializeAiConsent());
  }

  Future<void> _initializeAiConsent() async {
    try {
      final controller = ref.read(aiChatControllerProvider.notifier);
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
                'images may be processed by our third-party AI provider.',
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

  /// Lazy speech initialization with aggressive restart callbacks
  Future<bool> _ensureSpeechInitialized() async {
    if (_speechEnabled) return true;

    try {
      if (!kIsWeb) {
        var status = await Permission.microphone.request();
        if (status != PermissionStatus.granted) return false;
      }

      bool available = await _speech.initialize(
        onStatus: (status) {
          debugPrint('🎤 Status: $status');
          if (status == 'notListening' || status == 'done') {
            if (_isUserIntendingToListen && mounted) {
              // OS killed the listener against the user's will.
              // Snapshot whatever we have so far, then restart.
              _preListenText = _messageController.text.trim();
              debugPrint(
                  '🔄 Auto-restarting listener (OS timeout). Snapshot: "${_preListenText.length} chars"');
              Future.delayed(const Duration(milliseconds: 50), () {
                if (_isUserIntendingToListen && mounted) {
                  _startListeningSession();
                }
              });
            } else {
              if (mounted) setState(() => _isListening = false);
            }
          }
        },
        onError: (e) {
          debugPrint('❌ Voice Error: ${e.errorMsg}');
          if (_isUserIntendingToListen && mounted) {
            // Error (e.g. error_speech_timeout) — restart if user still wants to talk
            _preListenText = _messageController.text.trim();
            debugPrint(
                '🔄 Auto-restarting listener after error: ${e.errorMsg}');
            Future.delayed(const Duration(milliseconds: 50), () {
              if (_isUserIntendingToListen && mounted) {
                _startListeningSession();
              }
            });
          } else {
            if (mounted) {
              setState(() => _isListening = false);
            }
          }
        },
        debugLogging: true,
      );

      if (mounted) {
        setState(() => _speechEnabled = available);
      }
      return available;
    } catch (e) {
      debugPrint("❌ Init Exception: $e");
      return false;
    }
  }

  /// Internal: starts a single listen() session that appends to _preListenText.
  void _startListeningSession() {
    _speech.listen(
      onResult: (result) {
        final recognized = result.recognizedWords;
        final appended =
            _preListenText.isEmpty ? recognized : '$_preListenText $recognized';
        if (mounted) {
          setState(() {
            _messageController.text = appended;
            _messageController.selection = TextSelection.fromPosition(
              TextPosition(offset: _messageController.text.length),
            );
          });
        }
      },
    );
  }

  void _toggleListening() async {
    final isAvailable = await _ensureSpeechInitialized();

    if (!isAvailable) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
              content: Text("Microphone access denied or not available.")),
        );
      }
      return;
    }

    if (_isUserIntendingToListen) {
      // ── USER TAPS STOP ──
      _isUserIntendingToListen = false;
      _speech.stop();
      setState(() => _isListening = false);
    } else {
      // ── USER TAPS START ──
      _preListenText = _messageController.text.trim();
      _isUserIntendingToListen = true;
      setState(() => _isListening = true);
      _startListeningSession();
    }
  }

  @override
  void dispose() {
    _isUserIntendingToListen = false; // Kill the restart loop before disposing
    _messageController.dispose();
    _scrollController.dispose();
    _speech.stop();
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
    setState(() => _isUploadingImage = true);
    try {
      final image = await ref
          .read(imageUploadServiceProvider)
          .pickAndUploadTemporaryAiImage();
      if (image != null && mounted) {
        setState(() {
          _stagedImageUrl = image.url;
          _stagedImagePublicId = image.publicId;
        });
      }
    } catch (e) {
      debugPrint('[AiChatScreen] image staging failed: $e');
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
      });
    }
    if (publicId != null) {
      await ref
          .read(aiChatControllerProvider.notifier)
          .deleteTemporaryImage(publicId);
    }
  }

  /// Send message with optional staged image
  void _sendMessage() {
    final chatState = ref.read(aiChatControllerProvider);
    if (chatState.isLoading || _isUploadingImage) return;

    final text = _messageController.text.trim();
    final imageUrl = _stagedImageUrl;
    final imagePublicId = _stagedImagePublicId;

    // Need either text or an image
    if (text.isEmpty && imageUrl == null) return;

    final messageText = text.isNotEmpty ? text : "Analyze this image";

    ref.read(aiChatControllerProvider.notifier).sendMessage(messageText,
        imageUrl: imageUrl,
        imagePublicId: imagePublicId,
        language: _selectedLanguage);

    _messageController.clear();
    setState(() {
      _stagedImageUrl = null;
      _stagedImagePublicId = null;
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
                      .read(aiChatControllerProvider.notifier)
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
          ],
        ),
      ),
    );
  }

  /// Shows the "End Consultation" exit dialog with three options.
  Future<void> _showExitDialog() async {
    final shouldClose = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) => AlertDialog(
        title: const Text('End Consultation'),
        content: const Text(
          'This chat is ephemeral — all messages will be discarded when you leave.\n\n'
          'Would you like to save a summary to your Health Vault before exiting?',
        ),
        actions: [
          // ── Cancel ──────────────────────────────────────────────────────
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('Cancel'),
          ),

          // ── Exit & Delete ────────────────────────────────────────────────
          TextButton(
            style: TextButton.styleFrom(foregroundColor: Colors.redAccent),
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text('Exit & Delete'),
          ),

          // ── Exit & Save ──────────────────────────────────────────────────
          FilledButton.icon(
            icon: const Icon(Icons.health_and_safety_outlined, size: 18),
            label: const Text('Exit & Save'),
            onPressed: () async {
              Navigator.of(dialogContext)
                  .pop(false); // keep screen alive for now
              await _deleteStagedImage();
              if (!mounted) return;
              final success = await ref
                  .read(aiChatControllerProvider.notifier)
                  .saveSummary();
              if (!mounted) return;
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(
                  content: Text(
                    success
                        ? '✅ Summary saved to Health Vault!'
                        : '⚠️ Summary save failed. Exiting anyway.',
                  ),
                  duration: const Duration(seconds: 2),
                ),
              );
              if (mounted) Navigator.of(context).pop();
            },
          ),
        ],
      ),
    );

    if (shouldClose == true && mounted) {
      await _deleteStagedImage();
      if (!mounted) return;
      Navigator.of(context).pop();
    }
  }

  @override
  Widget build(BuildContext context) {
    final chatState = ref.watch(aiChatControllerProvider);
    final userAsync = ref.watch(userProvider);
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;

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
              icon: Icon(Icons.language, color: theme.colorScheme.onSurface),
              onSelected: (String lang) {
                setState(() => _selectedLanguage = lang);
              },
              color: theme.colorScheme.surface,
              shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12)),
              elevation: 4,
              itemBuilder: (BuildContext context) {
                return ['English', 'Nigerian Pidgin', 'Yoruba', 'Hausa', 'Igbo']
                    .map((String choice) {
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
            Expanded(
              child: _checkingConsent || !_hasAiConsent
                  ? const Center(child: CircularProgressIndicator())
                  : chatState.messages.isEmpty
                      ? _buildEmptyState(theme)
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
                              !_isUploadingImage
                          ? _showAttachmentMenu
                          : null,
                    ),
                    Expanded(
                      child: TextField(
                        controller: _messageController,
                        enabled: _hasAiConsent &&
                            !chatState.isLoading &&
                            !_isUploadingImage,
                        style: TextStyle(
                            color: isDark ? Colors.white : Colors.black87),
                        minLines: 1,
                        maxLines: 5,
                        keyboardType: TextInputType.multiline,
                        textInputAction: TextInputAction.newline,
                        decoration: InputDecoration(
                          hintText: _isListening
                              ? "Listening..."
                              : (_stagedImageUrl != null
                                  ? "Add a message..."
                                  : "Describe symptoms..."),
                          hintStyle: TextStyle(
                              color: _isListening
                                  ? Colors.redAccent
                                  : (isDark ? Colors.white54 : Colors.black54),
                              fontSize: 15),
                          border: InputBorder.none,
                          contentPadding: const EdgeInsets.symmetric(
                              horizontal: 8, vertical: 12),
                        ),
                      ),
                    ),
                    GestureDetector(
                      onTap: _hasAiConsent ? _toggleListening : null,
                      child: CircleAvatar(
                        backgroundColor: _isListening
                            ? Colors.redAccent
                            : Colors.transparent,
                        radius: 20,
                        child: Icon(
                          _isListening ? Icons.mic : Icons.mic_none,
                          color: _isListening
                              ? Colors.white
                              : Theme.of(context).colorScheme.onSurfaceVariant,
                          size: 22,
                        ),
                      ),
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
                                !_isUploadingImage
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
              child: _PremiumVoiceButton(
                text: text,
                language: _selectedLanguage,
                isDark: isDark,
              ),
            ),
        ],
      ),
    );
  }

  Widget _buildEmptyState(ThemeData theme) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Container(
            padding: const EdgeInsets.all(24),
            decoration: BoxDecoration(
              color: Colors.blue.withValues(alpha: 0.05),
              shape: BoxShape.circle,
            ),
            child: Icon(Icons.auto_awesome,
                size: 64, color: Colors.blue.withValues(alpha: 0.8)),
          ),
          const SizedBox(height: 24),
          Text("Hello! I'm MDQ+.",
              style: TextStyle(
                  color: theme.colorScheme.onSurfaceVariant, fontSize: 18)),
          const SizedBox(height: 8),
          Text("I can help assess your symptoms.",
              style: TextStyle(
                  color:
                      theme.colorScheme.onSurfaceVariant.withValues(alpha: 0.7),
                  fontSize: 14)),
        ],
      ),
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
    } catch (e) {
      debugPrint('Voice API Error: $e');
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
