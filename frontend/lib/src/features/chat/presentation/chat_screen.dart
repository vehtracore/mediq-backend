import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'package:mediq_app/src/features/auth/data/auth_repository.dart';
import 'package:mediq_app/src/features/chat/data/image_upload_service.dart';
import 'package:mediq_app/src/features/chat/presentation/full_screen_image_viewer.dart';
import 'package:mediq_app/src/features/doctors/data/doctor_repository.dart';

class ChatScreen extends ConsumerStatefulWidget {
  final int appointmentId;
  final String title;
  final bool isCompleted;
  final int? doctorId;

  const ChatScreen({
    super.key,
    required this.appointmentId,
    required this.title,
    this.isCompleted = false,
    this.doctorId,
  });

  @override
  ConsumerState<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends ConsumerState<ChatScreen> {
  final TextEditingController _msgController = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  WebSocketChannel? _channel;
  
  // State
  List<dynamic> _messages = [];
  bool _isLoading = true;
  int? _myUserId;
  
  // Pagination State
  String? _nextCursor;
  bool _hasMore = true;
  bool _isLoadingMore = false;

  String? _mdcnNumber;

  @override
  void initState() {
    super.initState();
    _initializeChat();
    
    // Add Scroll Listener for Pagination
    _scrollController.addListener(() {
      if (_scrollController.position.pixels >= 
          _scrollController.position.maxScrollExtent - 200) {
        _fetchMoreMessages();
      }
    });
  }

  Future<void> _fetchMoreMessages() async {
    if (_isLoadingMore || !_hasMore) return;
    
    setState(() {
      _isLoadingMore = true;
    });

    try {
      final dio = ref.read(dioProvider);
      final queryParam = _nextCursor != null ? "?cursor=$_nextCursor" : "";
      final response = await dio.get('/api/v1/p2p/history/${widget.appointmentId}$queryParam');
      
      List<dynamic> olderMessages = [];
      String? next;
      bool hasMoreData = false;
      
      // Handle both legacy (flat array) and new paginated object formats
      if (response.data is List) {
        olderMessages = response.data;
        hasMoreData = false; // Legacy backend doesn't support pagination, so no more after initial
      } else if (response.data is Map) {
        olderMessages = response.data['messages'] ?? [];
        next = response.data['next_cursor'];
        hasMoreData = response.data['has_more'] ?? false;
      }

      if (mounted) {
        setState(() {
          // Since reverse: true, older messages are appended to the end.
          // The backend returns order_by(created_at.asc()), which means older first.
          // We need newest first (0 = newest). So we reverse the older messages before appending.
          _messages.addAll(olderMessages.reversed.toList());
          _nextCursor = next;
          _hasMore = hasMoreData;
          _isLoadingMore = false;
        });
      }
    } catch (e) {
      print("Fetch More Error: $e");
      if (mounted) {
        setState(() {
          _isLoadingMore = false;
          _hasMore = false; // Stop trying if error occurs
        });
      }
    }
  }

  Future<void> _initializeChat() async {
    final user = await ref.read(authRepositoryProvider).getCurrentUser();
    if (user == null) return;
    _myUserId = int.tryParse(user.id.toString());

    if (widget.doctorId != null) {
      try {
        final doctor = await ref.read(doctorRepositoryProvider).getDoctorById(widget.doctorId!);
        if (mounted && doctor.licenseNumber != null) {
          setState(() { _mdcnNumber = doctor.licenseNumber; });
        }
      } catch (e) {
        print("Doctor fetch error: $e");
      }
    }

    final dio = ref.read(dioProvider);

    // Initial Load History
    try {
      final response = await dio.get('/api/v1/p2p/history/${widget.appointmentId}');
      if (mounted) {
        setState(() {
          // We are parsing the initial fetch.
          List<dynamic> initialMessages = [];
          if (response.data is List) {
             initialMessages = response.data;
             _hasMore = false; // Legacy backend gives all at once
          } else if (response.data is Map) {
             initialMessages = response.data['messages'] ?? [];
             _nextCursor = response.data['next_cursor'];
             _hasMore = response.data['has_more'] ?? false;
          }
          
          // Reversing the initial messages so index 0 is newest (bottom of screen)
          _messages = initialMessages.reversed.toList();
          _isLoading = false;
        });
      }
    } catch (e) {
      print("History Error: $e");
      if (mounted) setState(() => _isLoading = false);
    }

    // Connect WebSocket
    try {
      final baseUrl = dio.options.baseUrl;
      final cleanBaseUrl = baseUrl.endsWith('/')
          ? baseUrl.substring(0, baseUrl.length - 1)
          : baseUrl;
      String wsBase = cleanBaseUrl;
      if (wsBase.startsWith('https://')) {
        wsBase = wsBase.replaceFirst('https://', 'wss://');
      } else if (wsBase.startsWith('http://')) {
        wsBase = wsBase.replaceFirst('http://', 'ws://');
      }
      
      final wsUrl =
          '$wsBase/api/v1/p2p/live/${widget.appointmentId}/${user.id}';

      _channel = WebSocketChannel.connect(Uri.parse(wsUrl));

      _channel!.stream.listen((data) {
        final newMessage = jsonDecode(data);
        if (mounted) {
          setState(() {
            // New message comes in -> Goes to index 0 (bottom)
            _messages.insert(0, newMessage);
          });
        }
      }, onError: (error) => print("WS Error: $error"));
    } catch (e) {
      print("Connection Error: $e");
    }
  }

  void _sendMessage({String? content}) {
    final textToSend = content ?? _msgController.text.trim();
    if (textToSend.isEmpty) return;
    if (_channel == null) return;

    try {
      _channel!.sink.add(textToSend);
      if (content == null) {
        _msgController.clear();
      }
    } catch (e) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text("Failed to send")));
    }
  }

  Future<void> _handleImageUpload() async {
    final url = await ref.read(imageUploadServiceProvider).pickAndUploadImage();
    if (url != null) {
      _sendMessage(content: url);
    }
  }

  @override
  void dispose() {
    _channel?.sink.close();
    _msgController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;

    final baseUrl = ref.watch(dioProvider).options.baseUrl;
    final cleanBaseUrl = baseUrl.endsWith('/')
        ? baseUrl.substring(0, baseUrl.length - 1)
        : baseUrl;

    return Scaffold(
      backgroundColor: theme.scaffoldBackgroundColor, // ✅ Dynamic
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(widget.title, style: theme.textTheme.titleLarge),
            if (_mdcnNumber != null && _mdcnNumber!.isNotEmpty)
              Text("MDCN: $_mdcnNumber", style: const TextStyle(fontSize: 12, color: Colors.blue, fontWeight: FontWeight.bold)),
          ],
        ),
        backgroundColor: theme.appBarTheme.backgroundColor,
        foregroundColor: theme.appBarTheme.foregroundColor,
        elevation: 1,
      ),
      body: Column(
        children: [
          Expanded(
            child: _isLoading
                ? const Center(child: CircularProgressIndicator())
                : ListView.builder(
                    controller: _scrollController,
                    reverse: true, // ✅ Native chat layout (index 0 is bottom)
                    padding: const EdgeInsets.all(16),
                    itemCount: _messages.length + (_isLoadingMore ? 1 : 0),
                    itemBuilder: (context, index) {
                      // Show loader at the end of the list (top of screen due to reverse)
                      if (index == _messages.length) {
                        return const Padding(
                          padding: EdgeInsets.symmetric(vertical: 16.0),
                          child: Center(child: CircularProgressIndicator()),
                        );
                      }
                      
                      final msg = _messages[index];
                      final senderId =
                          int.tryParse(msg['sender_id'].toString());
                      final isMe = senderId == _myUserId;
                      final content = msg['content'] ?? '';
                      final isImage =
                          content.toString().startsWith('/static/') ||
                              content.toString().startsWith('http');

                      return Align(
                        alignment:
                            isMe ? Alignment.centerRight : Alignment.centerLeft,
                        child: Container(
                          margin: const EdgeInsets.only(bottom: 8),
                          padding: const EdgeInsets.symmetric(
                              horizontal: 14, vertical: 10),
                          constraints: BoxConstraints(
                              maxWidth:
                                  MediaQuery.of(context).size.width * 0.75),
                          decoration: BoxDecoration(
                            color: isMe
                                ? Colors.blueAccent
                                : (isDark
                                    ? const Color(0xFF2C2C2C)
                                    : Colors.white), // ✅ Dynamic Bubble
                            borderRadius: BorderRadius.circular(12),
                          ),
                          child: isImage
                              ? GestureDetector(
                                  onTap: () {
                                    final fullUrl = content.startsWith('http')
                                        ? content
                                        : "$cleanBaseUrl$content";
                                    Navigator.of(context).push(
                                      MaterialPageRoute(
                                        builder: (_) => FullScreenImageViewer(
                                          imageUrl: fullUrl,
                                        ),
                                      ),
                                    );
                                  },
                                  child: ClipRRect(
                                    borderRadius: BorderRadius.circular(8),
                                    child: Image.network(
                                      content.startsWith('http')
                                          ? content
                                          : "$cleanBaseUrl$content",
                                      height: 200,
                                      width: 200,
                                      fit: BoxFit.cover,
                                      errorBuilder: (c, e, s) => const Icon(
                                          Icons.broken_image,
                                          color: Colors.white),
                                    ),
                                  ),
                                )
                              : Text(
                                  content,
                                  style: TextStyle(
                                    color: isMe
                                        ? Colors.white
                                        : (isDark
                                            ? Colors.white
                                            : Colors.black87), // ✅ Dynamic Text
                                    fontSize: 16,
                                  ),
                                ),
                        ),
                      );
                    },
                  ),
          ),
          widget.isCompleted
              ? Container(
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
                  color: theme.cardTheme.color,
                  width: double.infinity,
                  child: const SafeArea(
                    child: Text(
                      "This consultation has ended.",
                      textAlign: TextAlign.center,
                      style: TextStyle(fontWeight: FontWeight.bold, color: Colors.grey),
                    ),
                  ),
                )
              : Container(
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                  color: theme.cardTheme.color, // ✅ Dynamic Input Area
                  child: SafeArea(
              child: Row(
                children: [
                  IconButton(
                    icon: Icon(Icons.add_photo_alternate,
                        color: theme.iconTheme.color),
                    onPressed: _handleImageUpload,
                  ),
                  Expanded(
                    child: TextField(
                      controller: _msgController,
                      style: theme.textTheme.bodyLarge, // ✅ Dynamic Text
                      minLines: 1,
                      maxLines: 5,
                      keyboardType: TextInputType.multiline,
                      textInputAction: TextInputAction.newline,
                      decoration: InputDecoration(
                        hintText: "Type a message...",
                        hintStyle: TextStyle(color: Colors.grey[400]),
                        filled: true,
                        fillColor: isDark
                            ? const Color(0xFF1E1E1E)
                            : Colors.grey[100], // ✅ Dynamic Field
                        border: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(24),
                            borderSide: BorderSide.none),
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  CircleAvatar(
                    backgroundColor: Colors.blueAccent,
                    child: IconButton(
                      icon:
                          const Icon(Icons.send, color: Colors.white, size: 20),
                      onPressed: () => _sendMessage(),
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
}
