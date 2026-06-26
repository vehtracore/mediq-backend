import 'dart:async';

import 'package:agora_rtc_engine/agora_rtc_engine.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:go_router/go_router.dart';
import 'package:flutter/foundation.dart';
import '../data/video_repository.dart';
import 'consultation_countdown_badge.dart';

class VideoCallScreen extends ConsumerStatefulWidget {
  final int appointmentId;
  final bool isVoiceCall;

  const VideoCallScreen({
    super.key,
    required this.appointmentId,
    this.isVoiceCall = false, // Defaults to Video if not specified
  });

  @override
  ConsumerState<VideoCallScreen> createState() => _VideoCallScreenState();
}

class _VideoCallScreenState extends ConsumerState<VideoCallScreen> {
  int? _remoteUid;
  bool _localUserJoined = false;
  RtcEngine? _engine;
  bool _isLoading = true;
  bool _muted = false;
  late bool _cameraOff;
  Timer? _warningTimer;
  Timer? _endTimer;
  DateTime? _videoEndsAt;
  DateTime? _messagesEndAt;
  bool _timeLimitHandled = false;

  @override
  void initState() {
    super.initState();
    // Initialize camera state based on the incoming request type
    _cameraOff = widget.isVoiceCall;
    _initAgora();
  }

  Future<void> _initAgora() async {
    // 1. Permissions: Request Microphone always. Request Camera only if Video call.
    if (!kIsWeb) {
      await [Permission.microphone].request();
      if (!widget.isVoiceCall) {
        await [Permission.camera].request();
      }
    }

    try {
      // 2. Fetch Token from Backend
      final data = await ref
          .read(videoRepositoryProvider)
          .getConnectionData(widget.appointmentId);
      final warningAt = DateTime.parse(data['warning_at'] as String).toLocal();
      final videoEndsAt =
          DateTime.parse(data['video_ends_at'] as String).toLocal();
      final messagesEndAt =
          DateTime.parse(data['messages_end_at'] as String).toLocal();
      if (mounted) {
        setState(() {
          _videoEndsAt = videoEndsAt;
          _messagesEndAt = messagesEndAt;
        });
      }

      _engine = createAgoraRtcEngine();
      await _engine!.initialize(
        RtcEngineContext(
          appId: data['app_id'],
          channelProfile: ChannelProfileType.channelProfileCommunication,
        ),
      );

      _engine!.registerEventHandler(
        RtcEngineEventHandler(
          onJoinChannelSuccess: (RtcConnection connection, int elapsed) {
            if (mounted) setState(() => _localUserJoined = true);
          },
          onUserJoined: (RtcConnection connection, int remoteUid, int elapsed) {
            if (mounted) setState(() => _remoteUid = remoteUid);
          },
          onUserOffline: (
            RtcConnection connection,
            int remoteUid,
            UserOfflineReasonType reason,
          ) {
            if (mounted) {
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text("User Left Call")),
              );
              context.pop();
            }
          },
        ),
      );

      await _engine!.setClientRole(role: ClientRoleType.clientRoleBroadcaster);
      await _engine!.enableAudio();

      // 3. Handle Video State Logic
      if (widget.isVoiceCall) {
        await _engine!.disableVideo(); // Bandwidth Saver
      } else {
        await _engine!.enableVideo();
        await _engine!.startPreview();
      }

      // 4. Join Channel
      await _engine!.joinChannel(
        token: data['token'],
        channelId: data['channel'],
        uid: data['uid'],
        options: ChannelMediaOptions(
          // Important: Tell Agora whether to send video packets or not
          publishCameraTrack: !widget.isVoiceCall,
          publishMicrophoneTrack: true,
          clientRoleType: ClientRoleType.clientRoleBroadcaster,
        ),
      );
      _scheduleTimeLimit(
        warningAt: warningAt,
        videoEndsAt: videoEndsAt,
      );

      if (mounted) setState(() => _isLoading = false);
    } catch (e) {
      debugPrint('[VideoCall] Unable to join consultation: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text(
              "Video service is temporarily unavailable. Please try again.",
            ),
            backgroundColor: Colors.red,
          ),
        );
        context.pop();
      }
    }
  }

  void _scheduleTimeLimit({
    required DateTime warningAt,
    required DateTime videoEndsAt,
  }) {
    final now = DateTime.now();
    final warningDelay = warningAt.difference(now);
    if (warningDelay.isNegative) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _showTimeWarning());
    } else {
      _warningTimer = Timer(warningDelay, _showTimeWarning);
    }

    final endDelay = videoEndsAt.difference(now);
    if (endDelay.isNegative) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _endForTimeLimit());
    } else {
      _endTimer = Timer(endDelay, _endForTimeLimit);
    }
  }

  void _showTimeWarning() {
    if (!mounted || _timeLimitHandled) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text("5 minutes remaining in this consultation video."),
        duration: Duration(seconds: 8),
      ),
    );
  }

  Future<void> _endForTimeLimit() async {
    if (!mounted || _timeLimitHandled) return;
    _timeLimitHandled = true;
    await _engine?.leaveChannel();
    if (!mounted) return;
    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) => AlertDialog(
        title: const Text("Video consultation ended"),
        content: const Text(
          "You can continue messaging for 10 minutes to wrap up the consultation.",
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(),
            child: const Text("Continue to messages"),
          ),
        ],
      ),
    );
    if (mounted) context.pop();
  }

  // Toggle Camera In-Call
  Future<void> _toggleCamera() async {
    if (_engine == null) return;

    if (_cameraOff) {
      // Turning ON
      await [Permission.camera].request(); // Ask permission just in case
      await _engine!.enableVideo();
      await _engine!.startPreview();
      // Update channel options to start sending video
      await _engine!.updateChannelMediaOptions(
        const ChannelMediaOptions(publishCameraTrack: true),
      );
    } else {
      // Turning OFF
      await _engine!.disableVideo();
      await _engine!.updateChannelMediaOptions(
        const ChannelMediaOptions(publishCameraTrack: false),
      );
    }
    setState(() => _cameraOff = !_cameraOff);
  }

  @override
  void dispose() {
    _warningTimer?.cancel();
    _endTimer?.cancel();
    _engine?.leaveChannel();
    _engine?.release();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.grey[900],
      body: Stack(
        children: [
          // 1. REMOTE USER VIEW
          Center(
            child: _remoteUid != null
                ? AgoraVideoView(
                    controller: VideoViewController.remote(
                      rtcEngine: _engine!,
                      canvas: VideoCanvas(uid: _remoteUid),
                      connection: RtcConnection(
                        channelId: "appt_${widget.appointmentId}",
                      ),
                    ),
                  )
                : _buildPlaceholder(
                    icon: Icons.person,
                    label:
                        _isLoading ? "Connecting..." : "Waiting for other...",
                  ),
          ),

          Positioned(
            top: 48,
            left: 0,
            right: 0,
            child: Center(
              child: ConsultationCountdownBadge(
                videoEndsAt: _videoEndsAt,
                messagesEndAt: _messagesEndAt,
                consultationStarted: _videoEndsAt != null,
                isClosed: _timeLimitHandled,
              ),
            ),
          ),

          // 2. LOCAL USER VIEW (Picture-in-Picture)
          // Only show if Camera is ON
          if (_localUserJoined && !_cameraOff)
            Positioned(
              right: 20,
              top: 50,
              child: ClipRRect(
                borderRadius: BorderRadius.circular(12),
                child: SizedBox(
                  width: 120,
                  height: 160,
                  child: AgoraVideoView(
                    controller: VideoViewController(
                      rtcEngine: _engine!,
                      canvas: const VideoCanvas(uid: 0),
                    ),
                  ),
                ),
              ),
            ),

          // 3. CONTROL BAR
          Align(
            alignment: Alignment.bottomCenter,
            child: Container(
              margin: const EdgeInsets.only(bottom: 30),
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
              decoration: BoxDecoration(
                color: Colors.black54,
                borderRadius: BorderRadius.circular(30),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  // Mute
                  _buildControlBtn(
                    icon: _muted ? Icons.mic_off : Icons.mic,
                    color: _muted ? Colors.white : Colors.black,
                    bgColor: _muted ? Colors.red : Colors.white,
                    onTap: () {
                      _engine?.muteLocalAudioStream(!_muted);
                      setState(() => _muted = !_muted);
                    },
                  ),
                  const SizedBox(width: 20),

                  // End Call
                  _buildControlBtn(
                    icon: Icons.call_end,
                    color: Colors.white,
                    bgColor: Colors.red,
                    scale: 1.3,
                    onTap: () => context.pop(),
                  ),
                  const SizedBox(width: 20),

                  // Toggle Camera
                  _buildControlBtn(
                    icon: _cameraOff ? Icons.videocam_off : Icons.videocam,
                    color: Colors.black,
                    bgColor: _cameraOff ? Colors.grey : Colors.white,
                    onTap: _toggleCamera,
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildPlaceholder({required IconData icon, required String label}) {
    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        Icon(icon, size: 80, color: Colors.white38),
        const SizedBox(height: 16),
        Text(label, style: const TextStyle(color: Colors.white54)),
      ],
    );
  }

  Widget _buildControlBtn({
    required IconData icon,
    required Color color,
    required Color bgColor,
    required VoidCallback onTap,
    double scale = 1.0,
  }) {
    return Transform.scale(
      scale: scale,
      child: GestureDetector(
        onTap: onTap,
        child: CircleAvatar(
          radius: 24,
          backgroundColor: bgColor,
          child: Icon(icon, color: color),
        ),
      ),
    );
  }
}
