import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:go_router/go_router.dart';
import 'package:mediq_app/src/features/chat/presentation/chat_controller.dart';
import 'package:mediq_app/src/features/appointments/data/appointment_repository.dart';

class ChatScreen extends ConsumerStatefulWidget {
  final String chatTitle;
  final bool isAi;
  final int? appointmentId; // NEW: To ID the session

  const ChatScreen({
    super.key,
    this.chatTitle = "Health Assistant",
    this.isAi = true,
    this.appointmentId,
  });

  @override
  ConsumerState<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends ConsumerState<ChatScreen> {
  final TextEditingController _textController = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  late List<Map<String, dynamic>> _messages;

  @override
  void initState() {
    super.initState();
    if (widget.isAi) {
      _messages = [
        {
          "text": "Hello! I'm MDQplus. How can I help you today?",
          "isUser": false,
          "isLoading": false,
        },
      ];
    } else {
      _messages = [];
    }
  }

  final List<String> _suggestions = [
    "Check my symptoms",
    "Speak to a doctor",
    "Find a pharmacy",
    "Emergency help",
  ];

  Future<void> _handleSend([String? manualText]) async {
    final text = manualText ?? _textController.text.trim();
    if (text.isEmpty) return;

    setState(() {
      _messages.add({"text": text, "isUser": true, "isLoading": false});
      if (widget.isAi)
        _messages.add({
          "text": "Thinking...",
          "isUser": false,
          "isLoading": true,
        });
    });

    _textController.clear();
    _scrollToBottom();

    if (widget.isAi) {
      try {
        final response = await ref
            .read(chatControllerProvider.notifier)
            .sendMessage(text);
        if (!mounted) return;
        setState(() {
          _messages.last['text'] = response;
          _messages.last['isLoading'] = false;
        });
      } catch (e) {
        if (!mounted) return;
        if (e.toString().contains("LIMIT_REACHED")) {
          setState(() => _messages.removeLast());
          context.push('/subscription');
          return;
        }
        setState(() {
          _messages.last['text'] = "Connection Error.";
          _messages.last['isLoading'] = false;
        });
      }
    }
    _scrollToBottom();
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 400),
          curve: Curves.easeOutQuad,
        );
      }
    });
  }

  // --- NEW: END CONSULTATION LOGIC ---
  Future<void> _endConsultation() async {
    try {
      await ref
          .read(appointmentRepositoryProvider)
          .completeAppointment(widget.appointmentId!);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text("Consultation Completed"),
            backgroundColor: Colors.green,
          ),
        );
        context.pop(); // Exit Chat
      }
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text("Error: $e"), backgroundColor: Colors.red),
        );
    }
  }

  @override
  Widget build(BuildContext context) {
    final bool isInitialAi = widget.isAi && _messages.length == 1;
    final Color appBarColor = widget.isAi
        ? const Color(0xFF4A90E2)
        : Colors.white;
    final Color iconColor = widget.isAi ? Colors.white : Colors.black87;
    final Color textColor = widget.isAi
        ? Colors.white
        : const Color(0xFF2D3436);

    return Scaffold(
      backgroundColor: const Color(0xFFF9FAFB),
      appBar: AppBar(
        backgroundColor: appBarColor,
        elevation: 0,
        centerTitle: false,
        leading: IconButton(
          icon: Icon(Icons.arrow_back_ios_new_rounded, color: iconColor),
          onPressed: () => Navigator.of(context).pop(),
        ),
        title: Row(
          children: [
            Container(
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: widget.isAi
                    ? Colors.white.withOpacity(0.2)
                    : const Color(0xFF4A90E2).withOpacity(0.1),
                shape: BoxShape.circle,
              ),
              child: Icon(
                widget.isAi ? Icons.smart_toy_rounded : Icons.person,
                size: 18,
                color: widget.isAi ? Colors.white : const Color(0xFF4A90E2),
              ),
            ),
            const SizedBox(width: 12),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  widget.chatTitle,
                  style: TextStyle(
                    color: textColor,
                    fontWeight: FontWeight.bold,
                    fontSize: 16,
                  ),
                ),
                if (!widget.isAi)
                  const Text(
                    "Online",
                    style: TextStyle(color: Colors.green, fontSize: 12),
                  ),
              ],
            ),
          ],
        ),
        actions: [
          if (!widget.isAi) ...[
            IconButton(
              icon: const Icon(Icons.videocam_outlined),
              color: iconColor,
              onPressed: () {},
            ),
            IconButton(
              icon: const Icon(Icons.call_outlined),
              color: iconColor,
              onPressed: () {},
            ),
            // --- END BUTTON (Only if we have an ID) ---
            if (widget.appointmentId != null)
              IconButton(
                icon: const Icon(Icons.check_circle, color: Colors.green),
                tooltip: "End Consultation",
                onPressed: () {
                  showDialog(
                    context: context,
                    builder: (ctx) => AlertDialog(
                      title: const Text("End Consultation?"),
                      content: const Text(
                        "This will mark the session as complete.",
                      ),
                      actions: [
                        TextButton(
                          onPressed: () => Navigator.pop(ctx),
                          child: const Text("Cancel"),
                        ),
                        TextButton(
                          onPressed: () {
                            Navigator.pop(ctx);
                            _endConsultation();
                          },
                          child: const Text(
                            "End Now",
                            style: TextStyle(color: Colors.red),
                          ),
                        ),
                      ],
                    ),
                  );
                },
              ),
            const SizedBox(width: 8),
          ],
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: _messages.isEmpty && !widget.isAi
                ? Center(
                    child: Text(
                      "Start consultation with ${widget.chatTitle}",
                      style: TextStyle(color: Colors.grey[400]),
                    ),
                  )
                : ListView.builder(
                    controller: _scrollController,
                    padding: const EdgeInsets.symmetric(
                      horizontal: 20,
                      vertical: 20,
                    ),
                    itemCount: _messages.length,
                    itemBuilder: (context, index) {
                      final msg = _messages[index];
                      return _buildMessageBubble(
                        msg['text'],
                        msg['isUser'],
                        isLoading: msg['isLoading'] ?? false,
                      );
                    },
                  ),
          ),
          if (isInitialAi)
            Container(
              height: 50,
              margin: const EdgeInsets.only(bottom: 10),
              child: ListView.separated(
                padding: const EdgeInsets.symmetric(horizontal: 20),
                scrollDirection: Axis.horizontal,
                itemCount: _suggestions.length,
                separatorBuilder: (_, __) => const SizedBox(width: 8),
                itemBuilder: (context, index) => ActionChip(
                  elevation: 0,
                  backgroundColor: Colors.white,
                  side: BorderSide(
                    color: const Color(0xFF4A90E2).withOpacity(0.2),
                  ),
                  label: Text(
                    _suggestions[index],
                    style: const TextStyle(
                      color: Color(0xFF4A90E2),
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(20),
                  ),
                  onPressed: () => _handleSend(_suggestions[index]),
                ),
              ),
            ),

          SafeArea(
            child: Container(
              margin: const EdgeInsets.fromLTRB(16, 0, 16, 16),
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(32),
                boxShadow: [
                  BoxShadow(
                    color: Colors.black.withOpacity(0.05),
                    blurRadius: 20,
                    offset: const Offset(0, 10),
                  ),
                ],
              ),
              child: Row(
                children: [
                  IconButton(
                    icon: Icon(
                      Icons.add_a_photo_rounded,
                      color: Colors.grey[400],
                    ),
                    onPressed: () {},
                  ),
                  Expanded(
                    child: TextField(
                      controller: _textController,
                      textCapitalization: TextCapitalization.sentences,
                      decoration: InputDecoration(
                        hintText: widget.isAi
                            ? "Describe symptoms..."
                            : "Type a message...",
                        hintStyle: TextStyle(color: Colors.grey[400]),
                        border: InputBorder.none,
                      ),
                      onSubmitted: (val) => _handleSend(),
                    ),
                  ),
                  const SizedBox(width: 12),
                  GestureDetector(
                    onTap: () => _handleSend(),
                    child: Container(
                      padding: const EdgeInsets.all(10),
                      decoration: const BoxDecoration(
                        shape: BoxShape.circle,
                        color: Color(0xFF4A90E2),
                      ),
                      child: const Icon(
                        Icons.arrow_upward_rounded,
                        color: Colors.white,
                        size: 20,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildMessageBubble(
    String text,
    bool isUser, {
    bool isLoading = false,
  }) {
    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.only(bottom: 16),
        constraints: BoxConstraints(
          maxWidth: MediaQuery.of(context).size.width * 0.8,
        ),
        decoration: BoxDecoration(
          color: isUser ? const Color(0xFF4A90E2) : Colors.white,
          borderRadius: BorderRadius.only(
            topLeft: const Radius.circular(24),
            topRight: const Radius.circular(24),
            bottomLeft: isUser
                ? const Radius.circular(24)
                : const Radius.circular(4),
            bottomRight: isUser
                ? const Radius.circular(4)
                : const Radius.circular(24),
          ),
          boxShadow: [
            if (!isUser)
              BoxShadow(
                color: Colors.grey.withOpacity(0.05),
                blurRadius: 10,
                offset: const Offset(0, 5),
              ),
          ],
        ),
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
        child: isLoading
            ? SizedBox(
                width: 40,
                height: 20,
                child: Center(
                  child: SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: Colors.grey[300],
                    ),
                  ),
                ),
              )
            : MarkdownBody(
                data: text,
                styleSheet: MarkdownStyleSheet(
                  p: TextStyle(
                    color: isUser ? Colors.white : const Color(0xFF2D3436),
                    fontSize: 15,
                    height: 1.5,
                  ),
                  strong: TextStyle(
                    color: isUser ? Colors.white : const Color(0xFF2D3436),
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
      ),
    );
  }
}
