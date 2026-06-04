import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'package:mediq_app/src/features/auth/data/auth_repository.dart';
import 'package:mediq_app/src/features/chat/data/image_upload_service.dart';
import 'package:mediq_app/src/features/chat/presentation/full_screen_image_viewer.dart';
import 'package:mediq_app/src/features/doctors/data/doctor_repository.dart';
import 'package:go_router/go_router.dart';

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

  bool _isPeerOnline = false;

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

        if (newMessage['type'] == 'presence') {
          if (newMessage['user_id'] != _myUserId) {
            if (mounted) {
              setState(() {
                _isPeerOnline = newMessage['status'] == 'online';
              });
            }
          }
          return;
        }

        if (newMessage['type'] == 'call_signal' && newMessage['user_id'] != _myUserId) {
          if (mounted) {
            final mediaType = newMessage['media'] == 'video' ? 'Video' : 'Voice';
            showDialog(
              context: context,
              builder: (ctx) => AlertDialog(
                title: Text("Incoming $mediaType Call"),
                content: Text("The doctor is inviting you to a $mediaType call."),
                actions: [
                  TextButton(
                    onPressed: () => Navigator.pop(ctx),
                    child: const Text("Decline"),
                  ),
                  FilledButton(
                    onPressed: () {
                      Navigator.pop(ctx);
                      // TODO: Navigate to WebRTC room
                    },
                    child: const Text("Join Call"),
                  ),
                ],
              ),
            );
          }
          return;
        }

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
      backgroundColor: theme.colorScheme.surface,
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(widget.title, style: theme.textTheme.titleLarge),
            if (_mdcnNumber != null && _mdcnNumber!.isNotEmpty)
              Text("MDCN: $_mdcnNumber", style: const TextStyle(fontSize: 12, color: Colors.blue, fontWeight: FontWeight.bold)),
            const SizedBox(height: 4),
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Container(
                  width: 8,
                  height: 8,
                  decoration: BoxDecoration(
                    color: _isPeerOnline ? Colors.greenAccent : Colors.grey,
                    shape: BoxShape.circle,
                  ),
                ),
                const SizedBox(width: 4),
                Text(
                  _isPeerOnline ? 'Online' : 'Offline',
                  style: TextStyle(
                    fontSize: 12,
                    color: _isPeerOnline ? Colors.greenAccent : Colors.grey,
                  ),
                ),
              ],
            ),
          ],
        ),
        actions: [
          Container(
            margin: const EdgeInsets.symmetric(horizontal: 4, vertical: 8),
            decoration: BoxDecoration(
              color: theme.colorScheme.primary.withOpacity(0.1),
              shape: BoxShape.circle,
            ),
            child: IconButton(
              icon: Icon(Icons.phone_outlined, color: theme.colorScheme.primary, size: 20),
              onPressed: () {
                if (_channel != null && _myUserId != null) {
                  _channel!.sink.add(jsonEncode({
                    "type": "call_signal",
                    "media": "audio",
                    "status": "initiated",
                    "user_id": _myUserId
                  }));
                }
                context.push('/video_call?type=voice', extra: widget.appointmentId);
              },
            ),
          ),
          Container(
            margin: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
            decoration: BoxDecoration(
              color: theme.colorScheme.primary.withOpacity(0.1),
              borderRadius: BorderRadius.circular(20),
            ),
            child: InkWell(
              borderRadius: BorderRadius.circular(20),
              onTap: () {
                if (_channel != null && _myUserId != null) {
                  _channel!.sink.add(jsonEncode({
                    "type": "call_signal",
                    "media": "video",
                    "status": "initiated",
                    "user_id": _myUserId
                  }));
                }
                context.push('/video_call', extra: widget.appointmentId);
              },
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 12),
                child: Row(
                  children: [
                    Icon(Icons.videocam_outlined, color: theme.colorScheme.primary, size: 20),
                    const SizedBox(width: 4),
                    Text(
                      "Video",
                      style: TextStyle(
                        color: theme.colorScheme.primary,
                        fontWeight: FontWeight.w600,
                        fontSize: 13,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
        backgroundColor: theme.appBarTheme.backgroundColor,
        foregroundColor: theme.appBarTheme.foregroundColor,
        elevation: 2,
        shadowColor: Colors.black.withOpacity(0.1),
        surfaceTintColor: Colors.transparent,
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
                      
                      if (content.toString().contains('"type":"call_signal"')) {
                        return const SizedBox.shrink();
                      }

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
                                : theme.cardTheme.color,
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
                                        : theme.colorScheme.onSurface,
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
                  padding: const EdgeInsets.only(left: 16, right: 16, bottom: 24, top: 12),
                  color: theme.colorScheme.surface,
                  child: SafeArea(
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 6),
                      decoration: BoxDecoration(
                        color: isDark ? Colors.white.withOpacity(0.05) : Colors.grey[200],
                        borderRadius: BorderRadius.circular(30),
                        border: Border.all(color: isDark ? Colors.white.withOpacity(0.05) : Colors.transparent),
                      ),
                      child: Row(
                        children: [
                          IconButton(
                            icon: Icon(Icons.add_photo_alternate, color: theme.colorScheme.onSurfaceVariant),
                            onPressed: _handleImageUpload,
                          ),
                          Expanded(
                            child: TextField(
                              controller: _msgController,
                              style: TextStyle(color: theme.colorScheme.onSurfaceVariant),
                              minLines: 1,
                              maxLines: 5,
                              keyboardType: TextInputType.multiline,
                              textInputAction: TextInputAction.newline,
                              decoration: InputDecoration(
                                hintText: "Type a message...",
                                hintStyle: TextStyle(color: theme.colorScheme.onSurfaceVariant.withOpacity(0.6)),
                                border: InputBorder.none,
                                contentPadding: const EdgeInsets.symmetric(horizontal: 8, vertical: 12),
                              ),
                            ),
                          ),
                          const SizedBox(width: 8),
                          Container(
                            decoration: BoxDecoration(
                              color: theme.colorScheme.primary,
                              shape: BoxShape.circle,
                            ),
                            child: IconButton(
                              onPressed: () => _sendMessage(),
                              icon: Icon(Icons.arrow_upward, color: theme.colorScheme.onPrimary, size: 20),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
        ],
      ),
    );
  }
}
