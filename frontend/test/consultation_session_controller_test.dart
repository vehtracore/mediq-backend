import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mediq_app/src/features/auth/data/auth_session_coordinator.dart';
import 'package:mediq_app/src/features/auth/data/user_model.dart';
import 'package:mediq_app/src/features/chat/data/websocket_auth_retry.dart';
import 'package:mediq_app/src/features/chat/presentation/consultation_chat_panel.dart';
import 'package:mediq_app/src/features/chat/presentation/consultation_session_controller.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('appointment-scoped consultation session', () {
    testWidgets('in-video panel clears unread and sends on the shared socket',
        (tester) async {
      final harness = _Harness();
      final session = harness.session;
      session.beginVideoTransition();
      await session.ensureStarted(live: true);
      harness.sockets.latest.emit(
        _message(id: 3, senderId: 9, content: 'Hello from chat'),
      );
      await tester.pump();
      expect(session.unreadCount, 1);
      session.setVideoChatVisible(true);

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            consultationSessionProvider.overrideWith(
              (ref, appointmentId) => session,
            ),
          ],
          child: const MaterialApp(
            home: Scaffold(body: ConsultationChatPanel(appointmentId: 7)),
          ),
        ),
      );
      await tester.pump();

      expect(find.text('Hello from chat'), findsOneWidget);
      expect(session.unreadCount, 0);
      await tester.enterText(find.byType(TextField), 'Reply without leaving');
      await tester.tap(find.byTooltip('Send message'));
      await tester.pump();

      expect(harness.sockets.connectCount, 1);
      expect(harness.sockets.latest.sent.last, 'Reply without leaving');
      session.setVideoChatVisible(false);
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump();
      expect(session.isVideoChatVisible, isFalse);
    });

    test('Chat to Video to Chat retains one WebSocket', () async {
      final harness = _Harness();
      final session = harness.session;

      session.attachChatSurface();
      await session.ensureStarted(live: true);
      session.setChatSurfaceVisible(false);
      session.beginVideoTransition();
      await session.ensureStarted(live: true);
      session.localVideoJoined(remotePresent: false);
      session.leaveVideo(returningToChat: true);
      session.setChatSurfaceVisible(true);

      expect(harness.sockets.connectCount, 1);
      expect(harness.presence.connectCount, 1);
      expect(harness.presence.published, contains(ConsultationMode.chat));
      await session.shutdown();
    });

    test('direct Video entry loads history and opens one WebSocket', () async {
      final harness = _Harness(
        history: [
          _message(id: 1, senderId: 9, content: 'Earlier message'),
        ],
      );

      harness.session.beginVideoTransition();
      await harness.session.ensureStarted(live: true);
      await harness.session.ensureStarted(live: true);

      expect(harness.session.messages.single['content'], 'Earlier message');
      expect(harness.sockets.connectCount, 1);
      expect(harness.presence.published.first, ConsultationMode.joiningVideo);
      await harness.session.shutdown();
    });

    test('message during Chat to Video transition is delivered once', () async {
      final harness = _Harness();
      final session = harness.session;
      session.attachChatSurface();
      await session.ensureStarted(live: true);
      session.setChatSurfaceVisible(false);
      session.beginVideoTransition();

      harness.sockets.latest.emit(
        _message(id: 41, senderId: 9, content: 'Can you see this?'),
      );
      await _flushEvents();
      harness.sockets.latest.emit(
        _message(id: 41, senderId: 9, content: 'Can you see this?'),
      );
      await _flushEvents();

      expect(session.messages.where((message) => message['id'] == 41),
          hasLength(1));
      expect(session.unreadCount, 1);
      await session.shutdown();
    });

    test(
        'Video badge increments, panel clears it, and panel send reuses socket',
        () async {
      final harness = _Harness();
      final session = harness.session;
      session.beginVideoTransition();
      await session.ensureStarted(live: true);
      session.localVideoJoined(remotePresent: false);

      harness.sockets.latest.emit(
        _message(id: 52, senderId: 9, content: 'Message from chat'),
      );
      await _flushEvents();
      expect(session.unreadCount, 1);

      session.setVideoChatVisible(true);
      expect(session.unreadCount, 0);
      expect(session.sendText('Reply from video'), isTrue);
      expect(harness.sockets.connectCount, 1);
      expect(harness.sockets.latest.sent.last, 'Reply from video');
      await session.shutdown();
    });

    test('message while Video exits remains once for returning Chat', () async {
      final harness = _Harness();
      final session = harness.session;
      session.attachChatSurface();
      await session.ensureStarted(live: true);
      session.setChatSurfaceVisible(false);
      session.beginVideoTransition();
      session.localVideoJoined(remotePresent: true);
      session.leaveVideo(returningToChat: true);

      harness.sockets.latest.emit(
        _message(id: 64, senderId: 9, content: 'While closing'),
      );
      await _flushEvents();
      session.setChatSurfaceVisible(true);

      expect(session.messages.where((message) => message['id'] == 64),
          hasLength(1));
      expect(session.unreadCount, 0);
      expect(harness.sockets.connectCount, 1);
      await session.shutdown();
    });

    test('mocked Agora callbacks publish deterministic Video states', () async {
      final harness = _Harness();
      final session = harness.session;
      final video = ConsultationVideoPresenceBridge(session);
      await session.ensureStarted(live: true);

      session.attachChatSurface();
      session.setChatSurfaceVisible(false);
      video.onTransitionStarted();
      video.onLocalJoined(remotePresent: false);
      video.onRemoteJoined();
      video.onRemoteLeft();
      expect(session.isVideoActive, isTrue);
      expect(harness.sockets.connectCount, 1);
      video.onLeft(returningToChat: true);

      expect(
        harness.presence.published,
        containsAllInOrder([
          ConsultationMode.chat,
          ConsultationMode.joiningVideo,
          ConsultationMode.videoWaiting,
          ConsultationMode.video,
          ConsultationMode.videoWaiting,
          ConsultationMode.chat,
        ]),
      );
      await session.shutdown();
    });

    test('app inactivity removes active presence and resume restores mode',
        () async {
      final harness = _Harness();
      final session = harness.session;
      session.attachChatSurface();
      await session.ensureStarted(live: true);

      session.handleAppLifecycleState(AppLifecycleState.paused);
      await _flushEvents();
      expect(harness.presence.untrackCount, 1);

      session.handleAppLifecycleState(AppLifecycleState.resumed);
      await _flushEvents();
      expect(harness.presence.published.last, ConsultationMode.chat);
      await session.shutdown();
    });

    test('peer waiting mode is exposed without claiming generic online state',
        () async {
      final harness = _Harness();
      await harness.session.ensureStarted(live: true);

      harness.presence.setPeerMode(ConsultationMode.videoWaiting);

      expect(harness.session.peerMode, ConsultationMode.videoWaiting);
      expect(harness.session.peerPresenceLabel, 'Waiting in video');
      expect(harness.session.peerParticipantLabel, 'Patient');
      await harness.session.shutdown();
    });

    test('unexpected and malformed presence identities are ignored', () {
      final mode = resolveExpectedPeerMode(
        expectedPeerPresenceId: 'peer-auth-id',
        entries: const [
          ConsultationPresenceEntry(
            key: 'unexpected-auth-id',
            payload: {
              'user_id': 'peer-auth-id',
              'mode': 'video',
              'updated_at': '2026-09-12T10:00:00Z',
              'version': 1,
            },
          ),
          ConsultationPresenceEntry(
            key: 'peer-auth-id',
            payload: {
              'user_id': 'spoofed-auth-id',
              'mode': 'video',
              'updated_at': '2026-09-12T10:01:00Z',
              'version': 1,
            },
          ),
          ConsultationPresenceEntry(
            key: 'peer-auth-id',
            payload: {
              'user_id': 'peer-auth-id',
              'mode': 'not-a-mode',
              'updated_at': 'not-a-time',
              'version': 1,
            },
          ),
        ],
      );

      expect(mode, isNull);
    });

    test('verified expected peer presence is accepted', () {
      final mode = resolveExpectedPeerMode(
        expectedPeerPresenceId: 'peer-auth-id',
        entries: const [
          ConsultationPresenceEntry(
            key: 'peer-auth-id',
            payload: {
              'user_id': 'peer-auth-id',
              'mode': 'video_waiting',
              'updated_at': '2026-09-12T10:00:00Z',
              'version': 1,
            },
          ),
        ],
      );

      expect(mode, ConsultationMode.videoWaiting);
    });

    test('presence channel is private and payload uses authenticated identity',
        () {
      final config = consultationPresenceChannelConfig('local-auth-id');
      final payload = consultationPresencePayload(
        authenticatedPresenceId: 'local-auth-id',
        mode: ConsultationMode.chat,
        updatedAt: DateTime.utc(2026, 9, 12, 10),
      );

      expect(config.private, isTrue);
      expect(config.enabled, isTrue);
      expect(config.key, 'local-auth-id');
      expect(payload['user_id'], 'local-auth-id');
      expect(payload['mode'], 'chat');
      expect(payload['version'], 1);
    });

    test('presence failure stays neutral while chat and video remain usable',
        () async {
      final harness = _Harness(presenceConnectFails: true);
      harness.session.beginVideoTransition();

      await harness.session.ensureStarted(live: true);

      expect(harness.session.peerMode, isNull);
      expect(harness.session.peerPresenceLabel, 'Not currently active');
      expect(harness.sockets.connectCount, 1);
      expect(harness.session.canSend, isTrue);
      expect(harness.session.isVideoActive, isTrue);
      await harness.session.shutdown();
    });

    test('terminal consultation denial becomes unavailable without reconnect',
        () async {
      final harness = _Harness();
      await harness.session.ensureStarted(live: true);

      await harness.sockets.latest.serverClose(4403);
      await _flushEvents();

      expect(harness.session.connectionState,
          ConsultationConnectionState.unavailable);
      expect(harness.sockets.connectCount, 1);
      expect(harness.presence.untrackCount, 1);
      await harness.session.shutdown();
    });

    test('account teardown closes each socket and presence exactly once',
        () async {
      final first = _Harness(appointmentId: 11);
      final second = _Harness(appointmentId: 12);
      final registry = ConsultationSessionRegistry()
        ..add(first.session)
        ..add(second.session);
      await first.session.ensureStarted(live: true);
      await second.session.ensureStarted(live: true);

      await registry.shutdownAll();
      await registry.shutdownAll();

      expect(first.sockets.latest.closeCount, 1);
      expect(second.sockets.latest.closeCount, 1);
      expect(first.presence.disposeCount, 1);
      expect(second.presence.disposeCount, 1);
    });
  });
}

Map<String, dynamic> _message({
  required int id,
  required int senderId,
  required String content,
}) =>
    {
      'id': id,
      'sender_id': senderId,
      'content': content,
      'created_at': '2026-09-11T10:00:00Z',
      'is_read': false,
    };

Future<void> _flushEvents() => Future<void>.delayed(Duration.zero);

class _Harness {
  _Harness({
    this.appointmentId = 7,
    List<Map<String, dynamic>> history = const [],
    bool presenceConnectFails = false,
  })  : sockets = _FakeSocketFactory(),
        presence = _FakePresence(connectFails: presenceConnectFails),
        historyGateway = _FakeHistoryGateway(history) {
    session = ConsultationSessionController(
      appointmentId: appointmentId,
      loadParticipant: () async => User(
        id: '5',
        email: 'doctor@example.com',
        firstName: 'Ada',
        lastName: 'Doctor',
        role: 'doctor',
      ),
      historyGateway: historyGateway,
      socketFactory: sockets,
      socketAuth: CoordinatedWebSocketAuth(
        AuthSessionCoordinator(gateway: _FakeAuthGateway()),
      ),
      presence: presence,
      apiBaseUrl: 'https://api.example.test',
      reconnectDelay: const Duration(days: 1),
    );
  }

  final int appointmentId;
  final _FakeSocketFactory sockets;
  final _FakePresence presence;
  final _FakeHistoryGateway historyGateway;
  late final ConsultationSessionController session;
}

class _FakeHistoryGateway implements ConsultationHistoryGateway {
  _FakeHistoryGateway(this.history);

  final List<Map<String, dynamic>> history;

  @override
  Future<ConsultationHistoryPage> fetchHistory(
    int appointmentId, {
    String? cursor,
  }) async =>
      ConsultationHistoryPage(
        messages: history,
        peerPresenceId: 'peer-auth-id',
      );
}

class _FakeSocketFactory implements ConsultationChatSocketFactory {
  final List<_FakeSocket> connections = [];

  int get connectCount => connections.length;
  _FakeSocket get latest => connections.last;

  @override
  ConsultationChatSocket connect(Uri uri) {
    final socket = _FakeSocket();
    connections.add(socket);
    return socket;
  }
}

class _FakeSocket implements ConsultationChatSocket {
  final StreamController<dynamic> _events = StreamController<dynamic>();
  final List<String> sent = [];
  int closeCount = 0;
  int? _closeCode = 1000;

  void emit(Map<String, dynamic> message) => _events.add(jsonEncode(message));

  Future<void> serverClose(int code) async {
    _closeCode = code;
    await _events.close();
  }

  @override
  int? get closeCode => _closeCode;

  @override
  Stream<dynamic> get stream => _events.stream;

  @override
  void send(String data) => sent.add(data);

  @override
  Future<void> close() {
    closeCount += 1;
    unawaited(_events.close());
    return Future.value();
  }
}

class _FakePresence implements ConsultationPresenceTransport {
  _FakePresence({this.connectFails = false});

  final bool connectFails;
  int connectCount = 0;
  int untrackCount = 0;
  int disposeCount = 0;
  final List<ConsultationMode> published = [];
  ValueChanged<ConsultationMode?>? _onPeerModeChanged;

  void setPeerMode(ConsultationMode? mode) => _onPeerModeChanged?.call(mode);

  @override
  Future<void> connect({
    required int appointmentId,
    required String? expectedPeerPresenceId,
    required ValueChanged<ConsultationMode?> onPeerModeChanged,
    required ValueChanged<bool> onConnectionChanged,
  }) async {
    connectCount += 1;
    if (connectFails) throw StateError('presence authorization denied');
    expect(expectedPeerPresenceId, 'peer-auth-id');
    _onPeerModeChanged = onPeerModeChanged;
    onConnectionChanged(true);
  }

  @override
  Future<void> dispose() async {
    disposeCount += 1;
  }

  @override
  Future<void> publish(ConsultationMode mode) async {
    published.add(mode);
  }

  @override
  Future<void> untrack() async {
    untrackCount += 1;
  }
}

class _FakeAuthGateway implements AuthSessionGateway {
  final AuthSessionSnapshot _session = AuthSessionSnapshot(
    accessToken: 'token',
    userId: 'supabase-user',
    expiresAt: DateTime.now().toUtc().add(const Duration(hours: 1)),
  );

  @override
  AuthSessionSnapshot? get currentSession => _session;

  @override
  Future<AuthSessionSnapshot> refreshSession() async => _session;

  @override
  Future<void> signOut() async {}
}
