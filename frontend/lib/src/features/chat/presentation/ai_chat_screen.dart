import 'dart:ui';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:speech_to_text/speech_to_text.dart' as stt;
import 'package:permission_handler/permission_handler.dart';
import 'package:flutter/foundation.dart' show kIsWeb; // 1. To detect Web

import 'package:mediq_app/src/features/chat/presentation/ai_chat_controller.dart';
import 'package:mediq_app/src/features/auth/presentation/user_controller.dart';
import 'package:mediq_app/src/features/chat/data/image_upload_service.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'package:go_router/go_router.dart';
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
  bool _isListening = false;
  bool _speechEnabled = false; // Tracks if init succeeded

  // --- IMAGE STAGING STATE ---
  String? _stagedImageUrl; // Cloudinary URL after upload
  bool _isUploadingImage = false;

  @override
  void initState() {
    super.initState();
    _speech = stt.SpeechToText();
  }

  /// Lazy speech initialization
  Future<bool> _ensureSpeechInitialized() async {
    if (_speechEnabled) return true;

    try {
      if (!kIsWeb) {
        var status = await Permission.microphone.request();
        if (status != PermissionStatus.granted) return false;
      }

      bool available = await _speech.initialize(
        onStatus: (status) {
          print('🎤 Status: $status');
          if (status == 'notListening' || status == 'done') {
            if (mounted) setState(() => _isListening = false);
          }
        },
        onError: (e) {
          print('❌ Voice Error: ${e.errorMsg}');
          if (mounted) setState(() => _isListening = false);
        },
        debugLogging: true,
      );

      if (mounted) {
        setState(() => _speechEnabled = available);
      }
      return available;
    } catch (e) {
      print("❌ Init Exception: $e");
      return false;
    }
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

    if (_isListening) {
      _speech.stop();
      setState(() => _isListening = false);
    } else {
      setState(() => _isListening = true);
      _speech.listen(
        onResult: (result) {
          setState(() {
            _messageController.text = result.recognizedWords;
            _messageController.selection = TextSelection.fromPosition(
              TextPosition(offset: _messageController.text.length),
            );
          });
        },
      );
    }
  }

  @override
  void dispose() {
    _messageController.dispose();
    _scrollController.dispose();
    _speech.stop();
    super.dispose();
  }

  void _scrollToBottom() {
    if (_scrollController.hasClients) {
      Future.delayed(const Duration(milliseconds: 100), () {
        if (_scrollController.hasClients) {
          _scrollController.animateTo(
            _scrollController.position.maxScrollExtent,
            duration: const Duration(milliseconds: 300),
            curve: Curves.easeOut,
          );
        }
      });
    }
  }

  /// Stage an image: pick → upload → store URL for preview
  Future<void> _stageImage() async {
    setState(() => _isUploadingImage = true);
    try {
      final url = await ref.read(imageUploadServiceProvider).pickAndUploadImage();
      if (url != null && mounted) {
        setState(() => _stagedImageUrl = url);
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text("Image upload failed: $e")),
        );
      }
    } finally {
      if (mounted) setState(() => _isUploadingImage = false);
    }
  }

  void _clearStagedImage() {
    setState(() => _stagedImageUrl = null);
  }

  /// Send message with optional staged image
  void _sendMessage() {
    final text = _messageController.text.trim();
    final imageUrl = _stagedImageUrl;

    // Need either text or an image
    if (text.isEmpty && imageUrl == null) return;

    final messageText = text.isNotEmpty ? text : "Analyze this image";

    ref.read(aiChatControllerProvider.notifier)
        .sendMessage(messageText, imageUrl: imageUrl, language: _selectedLanguage);

    _messageController.clear();
    setState(() => _stagedImageUrl = null);

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
                          Text("MDQ+ Premium Required", style: TextStyle(fontSize: 18)),
                        ],
                      ),
                      content: Text(
                        "AI Urinalysis is exclusively available for MDQ+ Premium subscribers. Upgrade your plan to unlock this and other advanced medical analysis features."
                      ),
                    ),
                  );
                  return;
                }

                // Premium User -> Proceed to scanner
                final result = await context.push<LabAnalysisResponse>('/lab_scanner');
                if (result != null) {
                  ref.read(aiChatControllerProvider.notifier).sendLabResult(result);
                  WidgetsBinding.instance.addPostFrameCallback((_) => _scrollToBottom());
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

  // Language selector removed in favor of PopupMenuButton in AppBar

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
        
        final shouldClose = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: const Text("End Session & Clear History?"),
            content: const Text(
                "This chat is ephemeral. All data will be wiped when you leave.\n\nWould you like to save a medical summary first?"),
            actions: [
               TextButton(
                onPressed: () => Navigator.of(context).pop(false), // Stay
                child: const Text("Cancel"),
              ),
              TextButton(
                onPressed: () {
                   Navigator.of(context).pop(true);
                },
                style: TextButton.styleFrom(foregroundColor: Colors.red),
                child: const Text("End & Delete"),
              ),
              FilledButton.icon(
                icon: const Icon(Icons.download),
                label: const Text("Save Summary"),
                onPressed: () async {
                  Navigator.of(context).pop(true);
                  await ref.read(aiChatControllerProvider.notifier).summarizeSession();
                  if (context.mounted) {
                     Navigator.of(context).pop();
                  }
                },
              ),
            ],
          ),
        );

        if (shouldClose == true) {
           if (context.mounted) Navigator.of(context).pop();
        }
      },
      child: Scaffold(
      backgroundColor: theme.colorScheme.surface,
      appBar: AppBar(
        title: Row(
          children: [
            const Icon(Icons.auto_awesome, color: Colors.blue),
            const SizedBox(width: 10),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text("MDQ+ AI Assistant", style: TextStyle(color: theme.colorScheme.onSurface, fontSize: 18, fontWeight: FontWeight.w600)),
                userAsync.when(
                  data: (user) => Text(
                    user?.isPremium == true
                        ? "Premium Mode ⚡"
                        : "Free Mode",
                    style: const TextStyle(fontSize: 10, color: Colors.greenAccent, fontWeight: FontWeight.w500, letterSpacing: 0.5),
                  ),
                  loading: () => Text("Connecting...",
                      style: TextStyle(fontSize: 10, color: theme.colorScheme.onSurfaceVariant)),
                  error: (_, __) => const SizedBox.shrink(),
                ),
              ],
            ),
          ],
        ),
        backgroundColor: isDark ? theme.colorScheme.surface : Colors.grey.shade50,
        foregroundColor: theme.colorScheme.onSurface,
        elevation: 2,
        shadowColor: Colors.black.withOpacity(0.1),
        surfaceTintColor: Colors.transparent,
        actions: [
          PopupMenuButton<String>(
            icon: Icon(Icons.language, color: theme.colorScheme.onSurface),
            onSelected: (String lang) {
              setState(() => _selectedLanguage = lang);
            },
            color: theme.colorScheme.surface,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
            elevation: 4,
            itemBuilder: (BuildContext context) {
              return ['English', 'Nigerian Pidgin', 'Yoruba', 'Hausa', 'Igbo'].map((String choice) {
                return PopupMenuItem<String>(
                  value: choice,
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(choice, style: TextStyle(color: _selectedLanguage == choice ? Colors.blue : theme.colorScheme.onSurface)),
                      if (_selectedLanguage == choice) const Icon(Icons.check, color: Colors.blue, size: 20),
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
          Expanded(
            child: chatState.messages.isEmpty
                ? _buildEmptyState(theme)
                : ListView.builder(
                    controller: _scrollController,
                    padding: const EdgeInsets.all(16),
                    itemCount: chatState.messages.length,
                    itemBuilder: (context, index) {
                      final msg = chatState.messages[index];
                      final isMe = msg['role'] == 'user';
                      
                      // 1. Check for Lab Result Message
                      if (msg['type'] == 'lab_result' && msg['lab_data'] != null) {
                        return LabResultBubble(
                          result: msg['lab_data'] as LabAnalysisResponse,
                          isMe: isMe,
                        );
                      }

                      return _buildMessageBubble(
                        msg['message'],
                        isMe,
                        imageUrl: msg['image'],
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
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
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
                        width: 60, height: 60,
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
                    onPressed: _clearStagedImage,
                    color: Colors.redAccent,
                    tooltip: "Remove image",
                  ),
                ],
              ),
            ),

          // --- UPLOADING INDICATOR ---
          if (_isUploadingImage)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              color: isDark ? Colors.grey[900] : Colors.grey[100],
              child: Row(
                children: [
                  const SizedBox(
                    width: 20, height: 20,
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
            padding: const EdgeInsets.only(left: 16, right: 16, bottom: 24, top: 12),
            color: theme.colorScheme.surface,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 6),
              decoration: BoxDecoration(
                color: isDark ? Colors.white.withOpacity(0.1) : Colors.grey[100],
                borderRadius: BorderRadius.circular(30),
                border: Border.all(color: isDark ? Colors.white.withOpacity(0.05) : Colors.transparent),
              ),
              child: Row(
                children: [
                  IconButton(
                    icon: const Icon(Icons.add_circle, color: Colors.blueAccent),
                    onPressed: _showAttachmentMenu,
                  ),
                  Expanded(
                    child: TextField(
                      controller: _messageController,
                      style: TextStyle(color: isDark ? Colors.white : Colors.black87),
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
                            color: _isListening ? Colors.redAccent : (isDark ? Colors.white54 : Colors.black54),
                            fontSize: 15),
                        border: InputBorder.none,
                        contentPadding: const EdgeInsets.symmetric(horizontal: 8, vertical: 12),
                      ),
                    ),
                  ),
                  GestureDetector(
                    onTap: _toggleListening,
                    child: CircleAvatar(
                      backgroundColor: _isListening ? Colors.redAccent : Colors.transparent,
                      radius: 20,
                      child: Icon(
                        _isListening ? Icons.mic : Icons.mic_none,
                        color: _isListening ? Colors.white : Theme.of(context).colorScheme.onSurfaceVariant,
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
                      onPressed: _sendMessage,
                      icon: const Icon(Icons.arrow_upward, color: Colors.white, size: 20),
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
      child: Container(
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
                            child: CircularProgressIndicator(strokeWidth: 2),
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
          ],
        ),
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
              color: Colors.blue.withOpacity(0.05),
              shape: BoxShape.circle,
            ),
            child: Icon(Icons.auto_awesome, size: 64, color: Colors.blue.withOpacity(0.8)),
          ),
          const SizedBox(height: 24),
          Text("Hello! I'm MDQ+.", style: TextStyle(color: theme.colorScheme.onSurfaceVariant, fontSize: 18)),
          const SizedBox(height: 8),
          Text("I can help assess your symptoms.", style: TextStyle(color: theme.colorScheme.onSurfaceVariant.withOpacity(0.7), fontSize: 14)),
        ],
      ),
    );
  }
}
