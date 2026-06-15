import 'dart:convert';
import 'dart:io';
import 'package:flutter/services.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'package:image_picker/image_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'package:mediq_app/src/features/auth/data/auth_repository.dart';
import 'package:mediq_app/src/features/chat/data/image_upload_service.dart';
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

  RealtimeChannel? _supabaseChannel;
  bool _isPeerWaitingOnVideo = false;
  bool _isPeerWaitingOnVoice = false;

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
                    onPressed: () {
                      Navigator.pop(ctx);
                      _supabaseChannel?.sendBroadcastMessage(
                        event: 'call_waiting',
                        payload: {'type': 'cancel', 'user_id': _myUserId},
                      );
                    },
                    child: const Text("Decline"),
                  ),
                  FilledButton(
                    onPressed: () {
                      Navigator.pop(ctx);
                      _supabaseChannel?.sendBroadcastMessage(
                        event: 'call_waiting',
                        payload: {'type': 'cancel', 'user_id': _myUserId},
                      );
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
            final msgIndex = _messages.indexWhere((m) => m['isSending'] == true && m['content'] == newMessage['content']);
            if (msgIndex != -1) {
              _messages[msgIndex] = newMessage;
            } else {
              _messages.insert(0, newMessage);

              if (newMessage['sender_id'] != _myUserId) {
                HapticFeedback.vibrate();
                SystemSound.play(SystemSoundType.click);
              }
            }
          });
        }
      }, onError: (error) => print("WS Error: $error"));

      // Setup Supabase Realtime Presence & Broadcast
      _supabaseChannel = Supabase.instance.client.channel('chat_room_${widget.appointmentId}');
      _supabaseChannel!
        ..onPresenceSync((payload) {
          final state = _supabaseChannel!.presenceState();
          bool peerOnline = false;
          for (final singleState in state) {
            for (final presence in singleState.presences) {
              final payload = presence.payload;
              if (payload['user_id'] != _myUserId) {
                peerOnline = true;
              }
            }
          }
          if (mounted) {
            setState(() {
              _isPeerOnline = peerOnline;
            });
          }
        })
        ..onPresenceJoin((payload) {
          if (mounted) setState(() {});
        })
        ..onPresenceLeave((payload) {
          if (mounted) setState(() {});
        })
        ..onBroadcast(event: 'call_waiting', callback: (payload) {
          final callPayload = payload['payload'] is Map
              ? Map<String, dynamic>.from(payload['payload'] as Map)
              : payload;

          if (callPayload['user_id'] != _myUserId) {
            if (mounted) {
              setState(() {
                if (callPayload['type'] == 'video_waiting') {
                  _isPeerWaitingOnVideo = true;
                } else if (callPayload['type'] == 'voice_waiting') {
                  _isPeerWaitingOnVoice = true;
                } else if (callPayload['type'] == 'cancel') {
                  _isPeerWaitingOnVideo = false;
                  _isPeerWaitingOnVoice = false;
                }
              });
            }
          }
        })
        ..subscribe((status, [error]) {
          if (status == RealtimeSubscribeStatus.subscribed) {
            _supabaseChannel!.track({
              'user_id': _myUserId,
              'online_at': DateTime.now().toIso8601String()
            });
          }
        });
    } catch (e) {
      print("Connection Error: $e");
    }
  }

  void _sendMessage({String? content, String? tempId}) {
    final textToSend = content ?? _msgController.text.trim();
    if (textToSend.isEmpty) return;
    if (_channel == null) return;

    if (tempId == null) {
      tempId = "temp_${DateTime.now().millisecondsSinceEpoch}";
      final tempMessage = {
        'id': tempId,
        'sender_id': _myUserId,
        'content': textToSend,
        'isSending': true,
      };
      setState(() {
        _messages.insert(0, tempMessage);
      });
    }

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
    final picker = ImagePicker();
    final XFile? image = await picker.pickImage(
      source: ImageSource.gallery,
      imageQuality: 90,
      maxWidth: 1920,
      maxHeight: 1920,
    );
    if (image == null) return;

    final tempId = "temp_${DateTime.now().millisecondsSinceEpoch}";
    final tempMessage = {
      'id': tempId,
      'sender_id': _myUserId,
      'content': "FILE:${image.path}",
      'isSending': true,
    };
    setState(() {
      _messages.insert(0, tempMessage);
    });

    final url = await ref.read(imageUploadServiceProvider).uploadFile(image);
    if (url != null) {
      setState(() {
        final idx = _messages.indexWhere((m) => m['id'] == tempId);
        if (idx != -1) {
          _messages[idx]['content'] = url;
        }
      });
      _sendMessage(content: url, tempId: tempId);
    } else {
      setState(() {
        _messages.removeWhere((m) => m['id'] == tempId);
      });
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Image upload failed")));
      }
    }
  }

  @override
  void dispose() {
    _supabaseChannel?.unsubscribe();
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
      body: Column(
        children: [
          SafeArea(
            bottom: false,
            child: Container(
              margin: const EdgeInsets.all(12),
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
              decoration: BoxDecoration(
                color: isDark ? Colors.white.withOpacity(0.05) : Colors.grey[200],
                borderRadius: BorderRadius.circular(30),
              ),
              child: Row(
                children: [
                  IconButton(
                    icon: const Icon(Icons.arrow_back),
                    onPressed: () => context.pop(),
                  ),
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(widget.title, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
                      if (_mdcnNumber != null && _mdcnNumber!.isNotEmpty)
                        Text("MDCN: $_mdcnNumber", style: const TextStyle(fontSize: 12, color: Colors.blue, fontWeight: FontWeight.bold)),
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
                  const Spacer(),
                  Container(
                    margin: const EdgeInsets.symmetric(horizontal: 4),
                    decoration: BoxDecoration(
                      color: theme.colorScheme.primary.withOpacity(0.1),
                      shape: BoxShape.circle,
                    ),
                    child: Stack(
                      clipBehavior: Clip.none,
                      children: [
                        IconButton(
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
                            _supabaseChannel?.sendBroadcastMessage(
                              event: 'call_waiting',
                              payload: {'type': 'voice_waiting', 'user_id': _myUserId},
                            );
                            context.push('/video_call?type=voice', extra: widget.appointmentId).then((_) {
                              _supabaseChannel?.sendBroadcastMessage(
                                event: 'call_waiting',
                                payload: {'type': 'cancel', 'user_id': _myUserId},
                              );
                            });
                          },
                        ),
                        if (_isPeerWaitingOnVoice)
                          const Positioned(
                            top: 4,
                            right: 4,
                            child: _BlinkingDot(color: Colors.green),
                          ),
                      ],
                    ),
                  ),
                  Container(
                    margin: const EdgeInsets.only(left: 4, right: 8),
                    decoration: BoxDecoration(
                      color: theme.colorScheme.primary.withOpacity(0.1),
                      shape: BoxShape.circle,
                    ),
                    child: Stack(
                      clipBehavior: Clip.none,
                      children: [
                        IconButton(
                          icon: Icon(Icons.videocam_outlined, color: theme.colorScheme.primary, size: 20),
                          onPressed: () {
                            if (_channel != null && _myUserId != null) {
                              _channel!.sink.add(jsonEncode({
                                "type": "call_signal",
                                "media": "video",
                                "status": "initiated",
                                "user_id": _myUserId
                              }));
                            }
                            _supabaseChannel?.sendBroadcastMessage(
                              event: 'call_waiting',
                              payload: {'type': 'video_waiting', 'user_id': _myUserId},
                            );
                            context.push('/video_call', extra: widget.appointmentId).then((_) {
                              _supabaseChannel?.sendBroadcastMessage(
                                event: 'call_waiting',
                                payload: {'type': 'cancel', 'user_id': _myUserId},
                              );
                            });
                          },
                        ),
                        if (_isPeerWaitingOnVideo)
                          const Positioned(
                            top: 4,
                            right: 4,
                            child: _BlinkingDot(color: Colors.green),
                          ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
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
                      final isSending = msg['isSending'] == true;
                      
                      if (content.toString().contains('"type":"call_signal"')) {
                        return const SizedBox.shrink();
                      }

                      final isImage =
                          content.toString().startsWith('/static/') ||
                          content.toString().startsWith('http') ||
                          content.toString().startsWith('FILE:');

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
                                    if (content.toString().startsWith('FILE:')) return;
                                    final fullUrl = content.startsWith('http')
                                        ? content
                                        : "$cleanBaseUrl$content";
                                    Navigator.push(
                                      context,
                                      MaterialPageRoute(
                                        builder: (_) => Scaffold(
                                          backgroundColor: Colors.black,
                                          appBar: AppBar(
                                            backgroundColor: Colors.black,
                                            iconTheme: const IconThemeData(color: Colors.white),
                                          ),
                                          body: Center(
                                            child: InteractiveViewer(
                                              child: Image.network(fullUrl),
                                            ),
                                          ),
                                        ),
                                      ),
                                    );
                                  },
                                  child: Stack(
                                    alignment: Alignment.center,
                                    children: [
                                      ClipRRect(
                                        borderRadius: BorderRadius.circular(8),
                                        child: content.toString().startsWith('FILE:')
                                            ? Image.file(
                                                File(content.toString().substring(5)),
                                                height: 200,
                                                width: 200,
                                                fit: BoxFit.cover,
                                              )
                                            : Image.network(
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
                                      if (isSending)
                                        Positioned.fill(
                                          child: Container(
                                            decoration: BoxDecoration(
                                              color: Colors.black45,
                                              borderRadius: BorderRadius.circular(8),
                                            ),
                                            child: const Center(
                                              child: CircularProgressIndicator(color: Colors.white),
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
                                          color: isMe
                                              ? Colors.white
                                              : theme.colorScheme.onSurface,
                                          fontSize: 16,
                                        ),
                                      ),
                                    ),
                                    if (isMe)
                                      Padding(
                                        padding: const EdgeInsets.only(left: 4.0),
                                        child: isSending
                                            ? const SizedBox(
                                                width: 12,
                                                height: 12,
                                                child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white70),
                                              )
                                            : const Icon(Icons.check, size: 14, color: Colors.white70),
                                      ),
                                  ],
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

class _BlinkingDot extends StatefulWidget {
  final Color color;
  const _BlinkingDot({required this.color});

  @override
  State<_BlinkingDot> createState() => _BlinkingDotState();
}

class _BlinkingDotState extends State<_BlinkingDot> with SingleTickerProviderStateMixin {
  late AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(vsync: this, duration: const Duration(milliseconds: 800))
      ..repeat(reverse: true);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return FadeTransition(
      opacity: _controller,
      child: Container(
        width: 10,
        height: 10,
        decoration: BoxDecoration(color: widget.color, shape: BoxShape.circle),
      ),
    );
  }
}
