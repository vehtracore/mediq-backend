import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:speech_to_text/speech_to_text.dart' as stt;
import 'package:permission_handler/permission_handler.dart';
import 'package:flutter/foundation.dart' show kIsWeb; // 1. To detect Web

import 'package:mediq_app/src/features/chat/presentation/ai_chat_controller.dart';
import 'package:mediq_app/src/features/auth/presentation/user_controller.dart';
import 'package:mediq_app/src/features/chat/data/image_upload_service.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';

class AiChatScreen extends ConsumerStatefulWidget {
  const AiChatScreen({super.key});

  @override
  ConsumerState<AiChatScreen> createState() => _AiChatScreenState();
}

class _AiChatScreenState extends ConsumerState<AiChatScreen> {
  final TextEditingController _messageController = TextEditingController();
  final ScrollController _scrollController = ScrollController();

  // --- VOICE STATE ---
  late stt.SpeechToText _speech;
  bool _isListening = false;
  bool _speechEnabled = false; // Tracks if init succeeded

  @override
  void initState() {
    super.initState();
    _speech = stt.SpeechToText();
    // 2. REMOVED _initSpeech() from here!
    // We wait for the user to click the button.
  }

  /// 3. New "Lazy" Initialization
  Future<bool> _ensureSpeechInitialized() async {
    if (_speechEnabled) return true; // Already ready

    try {
      // On mobile, request permission first. On web, skip (browser handles it).
      if (!kIsWeb) {
        var status = await Permission.microphone.request();
        if (status != PermissionStatus.granted) return false;
      }

      // Initialize - This MUST happen after a button click on Web
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
    // 4. Initialize ON DEMAND (The User Gesture)
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
      _scrollController.animateTo(
        _scrollController.position.maxScrollExtent,
        duration: const Duration(milliseconds: 300),
        curve: Curves.easeOut,
      );
    }
  }

  Future<void> _handleImageUpload() async {
    final url = await ref.read(imageUploadServiceProvider).pickAndUploadImage();
    if (url != null) {
      ref
          .read(aiChatControllerProvider.notifier)
          .sendMessage("Analyze this image", imageUrl: url);
    }
  }

  @override
  Widget build(BuildContext context) {
    final chatState = ref.watch(aiChatControllerProvider);
    final userAsync = ref.watch(userProvider);
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;

    final baseUrl = ref.watch(dioProvider).options.baseUrl;
    final cleanBaseUrl = baseUrl.endsWith('/')
        ? baseUrl.substring(0, baseUrl.length - 1)
        : baseUrl;

    WidgetsBinding.instance.addPostFrameCallback((_) => _scrollToBottom());

    return Scaffold(
      backgroundColor: theme.scaffoldBackgroundColor,
      appBar: AppBar(
        title: Row(
          children: [
            const Icon(Icons.auto_awesome, color: Colors.blue),
            const SizedBox(width: 10),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text("MDQ+ AI Assistant", style: theme.textTheme.titleMedium),
                userAsync.when(
                  data: (user) => Text(
                    user?.subscriptionTier == 'premium'
                        ? "Premium Mode ⚡"
                        : "Free Mode",
                    style: const TextStyle(fontSize: 10, color: Colors.green),
                  ),
                  loading: () => const Text("Connecting...",
                      style: TextStyle(fontSize: 10, color: Colors.grey)),
                  error: (_, __) => const SizedBox.shrink(),
                ),
              ],
            ),
          ],
        ),
        backgroundColor: theme.appBarTheme.backgroundColor,
        foregroundColor: theme.appBarTheme.foregroundColor,
        elevation: 1,
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
                      return _buildMessageBubble(
                        msg['message'],
                        isMe,
                        imageUrl: msg['image'],
                        baseUrl: cleanBaseUrl,
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
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: theme.cardTheme.color,
              boxShadow: isDark
                  ? []
                  : [const BoxShadow(color: Colors.black12, blurRadius: 5)],
            ),
            child: Row(
              children: [
                IconButton(
                  icon: Icon(Icons.add_photo_alternate,
                      color: theme.iconTheme.color),
                  onPressed: _handleImageUpload,
                ),
                Expanded(
                  child: TextField(
                    controller: _messageController,
                    style: theme.textTheme.bodyLarge,
                    decoration: InputDecoration(
                      hintText: _isListening
                          ? "Listening..."
                          : "Describe symptoms...",
                      hintStyle: TextStyle(
                          color: _isListening
                              ? Colors.redAccent
                              : (isDark ? Colors.grey[500] : Colors.grey[400])),
                      filled: true,
                      fillColor: theme.inputDecorationTheme.fillColor,
                      border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(30),
                          borderSide: BorderSide.none),
                      contentPadding: const EdgeInsets.symmetric(
                          horizontal: 20, vertical: 10),
                    ),
                    onSubmitted: (_) {
                      final text = _messageController.text.trim();
                      if (text.isNotEmpty) {
                        ref
                            .read(aiChatControllerProvider.notifier)
                            .sendMessage(text);
                        _messageController.clear();
                      }
                    },
                  ),
                ),
                const SizedBox(width: 8),

                // --- 🎙️ VOICE BUTTON (With Lazy Init) ---
                GestureDetector(
                  onTap: _toggleListening,
                  child: CircleAvatar(
                    backgroundColor: _isListening
                        ? Colors.redAccent
                        : (isDark ? Colors.grey[800] : Colors.grey[200]),
                    radius: 22,
                    child: _isListening
                        ? const Icon(Icons.mic, color: Colors.white, size: 20)
                        : Icon(Icons.mic_none,
                            color: theme.iconTheme.color, size: 20),
                  ),
                ),
                const SizedBox(width: 8),

                FloatingActionButton(
                  onPressed: () {
                    final text = _messageController.text.trim();
                    if (text.isNotEmpty) {
                      ref
                          .read(aiChatControllerProvider.notifier)
                          .sendMessage(text);
                      _messageController.clear();
                    }
                  },
                  mini: true,
                  backgroundColor: const Color(0xFF4A90E2),
                  child: const Icon(Icons.send, color: Colors.white),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildMessageBubble(String text, bool isMe,
      {String? imageUrl,
      String? baseUrl,
      required ThemeData theme,
      required bool isDark}) {
    return Align(
      alignment: isMe ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
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
            if (imageUrl != null && baseUrl != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 8.0),
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(8),
                  child: Image.network(
                    "$baseUrl$imageUrl",
                    height: 150,
                    width: 200,
                    fit: BoxFit.cover,
                    errorBuilder: (c, e, s) =>
                        const Icon(Icons.broken_image, color: Colors.white),
                  ),
                ),
              ),
            Text(
              text,
              style: TextStyle(
                  color: isMe
                      ? Colors.white
                      : (isDark ? Colors.white : Colors.black87)),
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
          Icon(Icons.medical_services_outlined,
              size: 64, color: Colors.blue[100]),
          const SizedBox(height: 16),
          Text("Hello! I'm MDQ+.", style: theme.textTheme.bodyLarge),
          Text("I can help assess your symptoms.",
              style: theme.textTheme.bodyMedium),
        ],
      ),
    );
  }
}
