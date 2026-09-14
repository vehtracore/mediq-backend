import 'dart:async';

import 'package:agora_rtc_engine/agora_rtc_engine.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:permission_handler/permission_handler.dart';

import '../data/video_repository.dart';
import 'consultation_chat_panel.dart';
import 'consultation_countdown_badge.dart';
import 'consultation_session_controller.dart';

class VideoCallScreen extends ConsumerStatefulWidget {
  const VideoCallScreen({
    super.key,
    required this.appointmentId,
    this.isVoiceCall = false,
  });

  final int appointmentId;
  final bool isVoiceCall;

  @override
  ConsumerState<VideoCallScreen> createState() => _VideoCallScreenState();
}

class _VideoCallScreenState extends ConsumerState<VideoCallScreen> {
  late final ConsultationSessionController _session;
  late final ConsultationVideoPresenceBridge _videoPresence;
  int? _remoteUid;
  int? _localAgoraUid;
  bool _localUserJoined = false;
  RtcEngine? _engine;
  bool _isLoading = true;
  bool _muted = false;
  late bool _cameraOff;
  bool _mediaReconnecting = false;
  bool _mediaUnavailable = false;
  bool _permissionDenied = false;
  bool _permissionPermanentlyDenied = false;
  bool _renewingToken = false;
  bool _exiting = false;
  bool _engineReleased = false;
  Timer? _warningTimer;
  Timer? _endTimer;
  DateTime? _videoEndsAt;
  DateTime? _messagesEndAt;
  bool _timeLimitHandled = false;

  @override
  void initState() {
    super.initState();
    _cameraOff = widget.isVoiceCall;
    _session = ref.read(consultationSessionProvider(widget.appointmentId));
    _videoPresence = ConsultationVideoPresenceBridge(_session);
    _videoPresence.onTransitionStarted();
    unawaited(_initAgora());
  }

  Future<void> _initAgora() async {
    await _session.ensureStarted(live: true);
    if (!mounted || _session.myUserId == null) {
      if (mounted) _showJoinFailure();
      return;
    }

    if (!kIsWeb && !await _requestMediaPermissions()) {
      return;
    }
    if (!mounted || _exiting) return;

    try {
      final data = await ref
          .read(videoRepositoryProvider)
          .getConnectionData(widget.appointmentId);
      _localAgoraUid = (data['uid'] as num).toInt();
      final warningAt = DateTime.parse(data['warning_at'] as String).toLocal();
      final videoEndsAt =
          DateTime.parse(data['video_ends_at'] as String).toLocal();
      final messagesEndAt =
          DateTime.parse(data['messages_end_at'] as String).toLocal();
      if (!mounted) return;
      setState(() {
        _videoEndsAt = videoEndsAt;
        _messagesEndAt = messagesEndAt;
      });

      final engine = createAgoraRtcEngine();
      _engine = engine;
      await engine.initialize(
        RtcEngineContext(
          appId: data['app_id'] as String,
          channelProfile: ChannelProfileType.channelProfileCommunication,
        ),
      );
      engine.registerEventHandler(_eventHandler());
      await engine.setClientRole(role: ClientRoleType.clientRoleBroadcaster);
      await engine.enableAudio();
      if (widget.isVoiceCall) {
        await engine.disableVideo();
      } else {
        await engine.enableVideo();
        await engine.startPreview();
      }
      await engine.joinChannel(
        token: data['token'] as String,
        channelId: data['channel'] as String,
        uid: _localAgoraUid!,
        options: ChannelMediaOptions(
          publishCameraTrack: !widget.isVoiceCall,
          publishMicrophoneTrack: true,
          clientRoleType: ClientRoleType.clientRoleBroadcaster,
        ),
      );
      _scheduleTimeLimit(warningAt: warningAt, videoEndsAt: videoEndsAt);
      if (mounted) setState(() => _isLoading = false);
    } catch (_) {
      debugPrint('[VideoCall] Unable to join consultation.');
      if (mounted) _showJoinFailure();
    }
  }

  Future<bool> _requestMediaPermissions() async {
    final permissions = <Permission>[
      Permission.microphone,
      if (!widget.isVoiceCall) Permission.camera,
    ];
    final statuses = await permissions.request();
    if (!mounted || _exiting) return false;
    final denied = statuses.values.any((status) => !status.isGranted);
    if (!denied) {
      setState(() {
        _permissionDenied = false;
        _permissionPermanentlyDenied = false;
      });
      return true;
    }

    final permanentlyDenied = statuses.values.any(
      (status) => status.isPermanentlyDenied || status.isRestricted,
    );
    _videoPresence.onJoinFailed(
      returningToChat: _session.isChatAttached,
    );
    setState(() {
      _isLoading = false;
      _mediaUnavailable = true;
      _permissionDenied = true;
      _permissionPermanentlyDenied = permanentlyDenied;
    });
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          widget.isVoiceCall
              ? 'Microphone permission is required for this call.'
              : 'Camera and microphone permissions are required for video.',
        ),
      ),
    );
    return false;
  }

  Future<void> _retryMediaSetup() async {
    if (_isLoading || _exiting || _engine != null) return;
    setState(() {
      _isLoading = true;
      _mediaUnavailable = false;
    });
    _videoPresence.onTransitionStarted();
    await _initAgora();
  }

  RtcEngineEventHandler _eventHandler() => RtcEngineEventHandler(
        onJoinChannelSuccess: (_, __) {
          if (!mounted || _exiting) return;
          setState(() {
            _localUserJoined = true;
            _mediaReconnecting = false;
            _mediaUnavailable = false;
          });
          _videoPresence.onLocalJoined(remotePresent: _remoteUid != null);
        },
        onRejoinChannelSuccess: (_, __) {
          if (!mounted || _exiting) return;
          setState(() {
            _localUserJoined = true;
            _mediaReconnecting = false;
            _mediaUnavailable = false;
          });
          _videoPresence.onReconnected(remotePresent: _remoteUid != null);
        },
        onUserJoined: (_, remoteUid, __) {
          if (!mounted || _exiting) return;
          setState(() => _remoteUid = remoteUid);
          _videoPresence.onRemoteJoined();
        },
        onUserOffline: (_, remoteUid, __) {
          if (!mounted || _exiting || _remoteUid != remoteUid) return;
          setState(() => _remoteUid = null);
          _videoPresence.onRemoteLeft();
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content:
                  Text('Participant left video. Waiting for them to return.'),
            ),
          );
        },
        onTokenPrivilegeWillExpire: (_, __) => unawaited(_renewAgoraToken()),
        onRequestToken: (_) => unawaited(_renewAgoraToken()),
        onConnectionStateChanged: (_, state, reason) {
          if (!mounted || _exiting) return;
          if (state == ConnectionStateType.connectionStateReconnecting) {
            setState(() => _mediaReconnecting = true);
            _videoPresence.onReconnecting();
            return;
          }
          if (state == ConnectionStateType.connectionStateConnected) {
            setState(() {
              _mediaReconnecting = false;
              _mediaUnavailable = false;
            });
            if (_localUserJoined) {
              _videoPresence.onReconnected(remotePresent: _remoteUid != null);
            }
            return;
          }
          if (state == ConnectionStateType.connectionStateFailed) {
            setState(() {
              _mediaReconnecting = false;
              _mediaUnavailable = true;
            });
            _videoPresence.onReconnecting();
            if (reason ==
                    ConnectionChangedReasonType.connectionChangedTokenExpired ||
                reason ==
                    ConnectionChangedReasonType.connectionChangedInvalidToken) {
              unawaited(_renewAgoraToken());
            }
          }
        },
      );

  Future<void> _renewAgoraToken() async {
    final uid = _localAgoraUid;
    final engine = _engine;
    if (_renewingToken || _exiting || uid == null || engine == null) return;
    _renewingToken = true;
    try {
      final data = await ref
          .read(videoRepositoryProvider)
          .getConnectionData(widget.appointmentId);
      final renewedUid = (data['uid'] as num).toInt();
      if (renewedUid != uid) {
        throw StateError('Agora renewal identity changed unexpectedly.');
      }
      if (!_exiting && _engine == engine) {
        await engine.renewToken(data['token'] as String);
      }
    } catch (_) {
      debugPrint('[VideoCall] media token renewal failed.');
      if (mounted && !_exiting) {
        setState(() => _mediaUnavailable = true);
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text(
                'Video connection needs attention. You can keep using chat.'),
          ),
        );
      }
    } finally {
      _renewingToken = false;
    }
  }

  void _showJoinFailure() {
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content:
            Text('Video service is temporarily unavailable. Please try again.'),
        backgroundColor: Colors.red,
      ),
    );
    unawaited(_leaveVideo());
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
        content: Text('5 minutes remaining in this consultation video.'),
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
        title: const Text('Video consultation ended'),
        content: const Text(
          'You can continue messaging for 10 minutes to wrap up the consultation.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('Continue to messages'),
          ),
        ],
      ),
    );
    if (mounted) await _leaveVideo();
  }

  Future<void> _toggleCamera() async {
    final engine = _engine;
    if (engine == null) return;
    if (_cameraOff) {
      final status = await Permission.camera.request();
      if (!status.isGranted) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('Camera permission is required to enable video.'),
            ),
          );
        }
        return;
      }
      await engine.enableVideo();
      await engine.startPreview();
      await engine.updateChannelMediaOptions(
        const ChannelMediaOptions(publishCameraTrack: true),
      );
    } else {
      await engine.disableVideo();
      await engine.updateChannelMediaOptions(
        const ChannelMediaOptions(publishCameraTrack: false),
      );
    }
    if (mounted) setState(() => _cameraOff = !_cameraOff);
  }

  Future<void> _openChat() async {
    _session.setVideoChatVisible(true);
    try {
      await showModalBottomSheet<void>(
        context: context,
        isScrollControlled: true,
        useSafeArea: true,
        builder: (_) => ConsultationChatPanel(
          appointmentId: widget.appointmentId,
        ),
      );
    } finally {
      _session.setVideoChatVisible(false);
    }
  }

  Future<void> _leaveVideo() async {
    if (_exiting) return;
    _exiting = true;
    _warningTimer?.cancel();
    _endTimer?.cancel();
    _videoPresence.onLeft(returningToChat: _session.isChatAttached);
    await _releaseAgora();
    if (mounted) context.pop();
  }

  Future<void> _releaseAgora() async {
    if (_engineReleased) return;
    _engineReleased = true;
    final engine = _engine;
    _engine = null;
    if (engine != null) {
      await engine.leaveChannel();
      await engine.release();
    }
  }

  @override
  void dispose() {
    _warningTimer?.cancel();
    _endTimer?.cancel();
    _session.setVideoChatVisible(false);
    if (!_exiting) {
      _exiting = true;
      _videoPresence.onLeft(returningToChat: _session.isChatAttached);
    }
    unawaited(_releaseAgora());
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final session =
        ref.watch(consultationSessionProvider(widget.appointmentId));
    return Scaffold(
      backgroundColor: Colors.grey[900],
      body: Stack(
        children: [
          Center(
            child: _remoteUid != null && _engine != null
                ? AgoraVideoView(
                    controller: VideoViewController.remote(
                      rtcEngine: _engine!,
                      canvas: VideoCanvas(uid: _remoteUid),
                      connection: RtcConnection(
                        channelId: 'appt_${widget.appointmentId}',
                      ),
                    ),
                  )
                : _buildPlaceholder(
                    icon: _mediaUnavailable
                        ? Icons.videocam_off_outlined
                        : Icons.person,
                    label: _waitingLabel(session),
                    showPermissionActions: _permissionDenied,
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
          if (_localUserJoined && !_cameraOff && _engine != null)
            Positioned(
              right: 20,
              top: 90,
              child: ClipRRect(
                borderRadius: BorderRadius.circular(8),
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
          Align(
            alignment: Alignment.bottomCenter,
            child: Container(
              margin: const EdgeInsets.only(bottom: 30),
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
              decoration: BoxDecoration(
                color: Colors.black54,
                borderRadius: BorderRadius.circular(30),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  _buildControlButton(
                    key: const Key('video_mic_control'),
                    tooltip: _muted ? 'Unmute' : 'Mute',
                    icon: _muted ? Icons.mic_off : Icons.mic,
                    color: _muted ? Colors.white : Colors.black,
                    backgroundColor: _muted ? Colors.red : Colors.white,
                    onPressed: () {
                      _engine?.muteLocalAudioStream(!_muted);
                      setState(() => _muted = !_muted);
                    },
                  ),
                  const SizedBox(width: 12),
                  _buildChatControl(session),
                  const SizedBox(width: 12),
                  _buildControlButton(
                    key: const Key('video_end_control'),
                    tooltip: 'Leave video',
                    icon: Icons.call_end,
                    color: Colors.white,
                    backgroundColor: Colors.red,
                    onPressed: _leaveVideo,
                  ),
                  const SizedBox(width: 12),
                  _buildControlButton(
                    key: const Key('video_camera_control'),
                    tooltip: _cameraOff ? 'Turn camera on' : 'Turn camera off',
                    icon: _cameraOff ? Icons.videocam_off : Icons.videocam,
                    color: Colors.black,
                    backgroundColor: _cameraOff ? Colors.grey : Colors.white,
                    onPressed: _toggleCamera,
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  String _waitingLabel(ConsultationSessionController session) {
    if (_isLoading) {
      return 'Connecting to video...';
    }
    if (_mediaReconnecting) {
      return 'Video is reconnecting';
    }
    if (_mediaUnavailable) {
      if (_permissionDenied) {
        return _permissionPermanentlyDenied
            ? 'Camera or microphone access is disabled in app settings.'
            : 'Camera or microphone permission was denied.';
      }
      return 'Video is unavailable. Chat is still available.';
    }
    final participant = session.peerParticipantLabel;
    return switch (session.peerMode) {
      ConsultationMode.chat => '$participant is in chat',
      ConsultationMode.joiningVideo => '$participant is joining video',
      ConsultationMode.videoWaiting => '$participant is waiting in video',
      ConsultationMode.video => 'Waiting for $participant video',
      ConsultationMode.reconnecting => '$participant is reconnecting',
      null => 'Waiting for ${participant.toLowerCase()} to join',
    };
  }

  Widget _buildChatControl(ConsultationSessionController session) {
    return Stack(
      clipBehavior: Clip.none,
      children: [
        _buildControlButton(
          key: const Key('video_chat_control'),
          tooltip: 'Open chat',
          icon: Icons.chat_bubble_outline,
          color: Colors.black,
          backgroundColor: Colors.white,
          onPressed: _openChat,
        ),
        if (session.unreadCount > 0)
          Positioned(
            right: -5,
            top: -7,
            child: Badge(
              key: const Key('video_chat_unread_badge'),
              label: Text(
                session.unreadCount > 99 ? '99+' : '${session.unreadCount}',
              ),
            ),
          ),
      ],
    );
  }

  Widget _buildPlaceholder({
    required IconData icon,
    required String label,
    required bool showPermissionActions,
  }) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 28),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(icon, size: 80, color: Colors.white38),
          const SizedBox(height: 16),
          Text(
            label,
            textAlign: TextAlign.center,
            style: const TextStyle(color: Colors.white70),
          ),
          if (showPermissionActions) ...[
            const SizedBox(height: 16),
            FilledButton(
              onPressed: _retryMediaSetup,
              child: const Text('Try again'),
            ),
            if (_permissionPermanentlyDenied)
              const TextButton(
                onPressed: openAppSettings,
                child: Text('Open app settings'),
              ),
          ],
        ],
      ),
    );
  }

  Widget _buildControlButton({
    required Key key,
    required String tooltip,
    required IconData icon,
    required Color color,
    required Color backgroundColor,
    required VoidCallback onPressed,
  }) {
    return IconButton(
      key: key,
      tooltip: tooltip,
      onPressed: onPressed,
      style: IconButton.styleFrom(
        fixedSize: const Size(48, 48),
        backgroundColor: backgroundColor,
        foregroundColor: color,
      ),
      icon: Icon(icon),
    );
  }
}
