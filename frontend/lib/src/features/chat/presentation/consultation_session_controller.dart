import 'dart:async';
import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart' hide User;
import 'package:web_socket_channel/web_socket_channel.dart';

import '../../../core/api/dio_client.dart';
import '../../auth/data/auth_session_coordinator.dart';
import '../../auth/data/user_model.dart';
import '../../auth/presentation/user_controller.dart';
import '../data/websocket_auth_retry.dart';

enum ConsultationMode {
  chat,
  joiningVideo,
  videoWaiting,
  video,
  reconnecting,
}

extension ConsultationModeCopy on ConsultationMode {
  String get wireValue => switch (this) {
        ConsultationMode.chat => 'chat',
        ConsultationMode.joiningVideo => 'joining_video',
        ConsultationMode.videoWaiting => 'video_waiting',
        ConsultationMode.video => 'video',
        ConsultationMode.reconnecting => 'reconnecting',
      };

  String get label => switch (this) {
        ConsultationMode.chat => 'In chat',
        ConsultationMode.joiningVideo => 'Joining video',
        ConsultationMode.videoWaiting => 'Waiting in video',
        ConsultationMode.video => 'In video',
        ConsultationMode.reconnecting => 'Reconnecting',
      };

  static ConsultationMode? fromWireValue(Object? value) => switch (value) {
        'chat' => ConsultationMode.chat,
        'joining_video' => ConsultationMode.joiningVideo,
        'video_waiting' => ConsultationMode.videoWaiting,
        'video' => ConsultationMode.video,
        'reconnecting' => ConsultationMode.reconnecting,
        _ => null,
      };
}

enum ConsultationConnectionState { connected, reconnecting, unavailable }

/// Maps Agora media callbacks onto consultation-mode presence without owning
/// camera, microphone, tokens, or the Agora engine itself.
class ConsultationVideoPresenceBridge {
  ConsultationVideoPresenceBridge(this._session);

  final ConsultationSessionController _session;

  void onTransitionStarted() => _session.beginVideoTransition();

  void onLocalJoined({required bool remotePresent}) =>
      _session.localVideoJoined(remotePresent: remotePresent);

  void onRemoteJoined() => _session.remoteVideoJoined();

  void onRemoteLeft() => _session.remoteVideoLeft();

  void onReconnecting() => _session.mediaReconnecting();

  void onReconnected({required bool remotePresent}) =>
      _session.mediaReconnected(remotePresent: remotePresent);

  void onJoinFailed({required bool returningToChat}) =>
      _session.videoJoinFailed(returningToChat: returningToChat);

  void onLeft({required bool returningToChat}) =>
      _session.leaveVideo(returningToChat: returningToChat);
}

class ConsultationHistoryPage {
  const ConsultationHistoryPage({
    required this.messages,
    this.nextCursor,
    this.hasMore = false,
    this.peerPresenceId,
  });

  final List<Map<String, dynamic>> messages;
  final String? nextCursor;
  final bool hasMore;
  final String? peerPresenceId;
}

abstract interface class ConsultationHistoryGateway {
  Future<ConsultationHistoryPage> fetchHistory(
    int appointmentId, {
    String? cursor,
  });
}

class DioConsultationHistoryGateway implements ConsultationHistoryGateway {
  DioConsultationHistoryGateway(this._dio);

  final Dio _dio;

  @override
  Future<ConsultationHistoryPage> fetchHistory(
    int appointmentId, {
    String? cursor,
  }) async {
    final response = await _dio.get(
      '/api/v1/p2p/history/$appointmentId',
      queryParameters: cursor == null ? null : {'cursor': cursor},
    );
    final data = response.data;
    if (data is List) {
      return ConsultationHistoryPage(
        messages: data
            .whereType<Map>()
            .map((item) => Map<String, dynamic>.from(item))
            .toList(),
      );
    }
    if (data is Map) {
      final rawMessages = data['messages'];
      return ConsultationHistoryPage(
        messages: rawMessages is List
            ? rawMessages
                .whereType<Map>()
                .map((item) => Map<String, dynamic>.from(item))
                .toList()
            : const [],
        nextCursor: data['next_cursor']?.toString(),
        hasMore: data['has_more'] == true,
        peerPresenceId: data['peer_presence_id']?.toString(),
      );
    }
    return const ConsultationHistoryPage(messages: []);
  }
}

abstract interface class ConsultationChatSocket {
  Stream<dynamic> get stream;
  int? get closeCode;
  void send(String data);
  Future<void> close();
}

abstract interface class ConsultationChatSocketFactory {
  ConsultationChatSocket connect(Uri uri);
}

class WebSocketConsultationChatSocketFactory
    implements ConsultationChatSocketFactory {
  const WebSocketConsultationChatSocketFactory();

  @override
  ConsultationChatSocket connect(Uri uri) =>
      _WebSocketConsultationChatSocket(WebSocketChannel.connect(uri));
}

class _WebSocketConsultationChatSocket implements ConsultationChatSocket {
  _WebSocketConsultationChatSocket(this._channel);

  final WebSocketChannel _channel;

  @override
  int? get closeCode => _channel.closeCode;

  @override
  Stream<dynamic> get stream => _channel.stream;

  @override
  void send(String data) => _channel.sink.add(data);

  @override
  Future<void> close() async => _channel.sink.close();
}

abstract interface class ConsultationPresenceTransport {
  Future<void> connect({
    required int appointmentId,
    required String? expectedPeerPresenceId,
    required ValueChanged<ConsultationMode?> onPeerModeChanged,
    required ValueChanged<bool> onConnectionChanged,
  });

  Future<void> publish(ConsultationMode mode);
  Future<void> untrack();
  Future<void> dispose();
}

class ConsultationPresenceEntry {
  const ConsultationPresenceEntry({
    required this.key,
    required this.payload,
  });

  final String key;
  final Map<String, dynamic> payload;
}

ConsultationMode? resolveExpectedPeerMode({
  required Iterable<ConsultationPresenceEntry> entries,
  required String expectedPeerPresenceId,
}) {
  DateTime? newestAt;
  ConsultationMode? newestMode;
  for (final entry in entries) {
    final payload = entry.payload;
    if (entry.key != expectedPeerPresenceId ||
        payload['user_id']?.toString() != expectedPeerPresenceId ||
        payload['version'] != 1) {
      continue;
    }
    final mode = ConsultationModeCopy.fromWireValue(payload['mode']);
    final updatedAt =
        DateTime.tryParse(payload['updated_at']?.toString() ?? '');
    if (mode == null || updatedAt == null) continue;
    if (newestAt == null || updatedAt.isAfter(newestAt)) {
      newestAt = updatedAt;
      newestMode = mode;
    }
  }
  return newestMode;
}

RealtimeChannelConfig consultationPresenceChannelConfig(
  String authenticatedPresenceId,
) =>
    RealtimeChannelConfig(
      private: true,
      enabled: true,
      key: authenticatedPresenceId,
    );

Map<String, dynamic> consultationPresencePayload({
  required String authenticatedPresenceId,
  required ConsultationMode mode,
  required DateTime updatedAt,
}) =>
    {
      'user_id': authenticatedPresenceId,
      'mode': mode.wireValue,
      'updated_at': updatedAt.toUtc().toIso8601String(),
      'version': 1,
    };

class SupabaseConsultationPresenceTransport
    implements ConsultationPresenceTransport {
  SupabaseConsultationPresenceTransport(this._client);

  final SupabaseClient _client;
  RealtimeChannel? _channel;
  String? _localPresenceId;
  String? _expectedPeerPresenceId;
  ConsultationMode? _pendingMode;
  bool _subscribed = false;
  ValueChanged<ConsultationMode?>? _onPeerModeChanged;
  ValueChanged<bool>? _onConnectionChanged;

  @override
  Future<void> connect({
    required int appointmentId,
    required String? expectedPeerPresenceId,
    required ValueChanged<ConsultationMode?> onPeerModeChanged,
    required ValueChanged<bool> onConnectionChanged,
  }) async {
    if (_channel != null) return;
    _onPeerModeChanged = onPeerModeChanged;
    _onConnectionChanged = onConnectionChanged;
    final localPresenceId = _client.auth.currentUser?.id;
    if (localPresenceId == null ||
        expectedPeerPresenceId == null ||
        expectedPeerPresenceId.isEmpty ||
        expectedPeerPresenceId == localPresenceId) {
      _failClosed();
      return;
    }
    _localPresenceId = localPresenceId;
    _expectedPeerPresenceId = expectedPeerPresenceId;
    final channel = _client.channel(
      'chat_room_$appointmentId',
      opts: consultationPresenceChannelConfig(localPresenceId),
    );
    _channel = channel;
    channel
      ..onPresenceSync((_) => _syncPeerMode())
      ..onPresenceJoin((_) => _syncPeerMode())
      ..onPresenceLeave((_) => _syncPeerMode())
      ..subscribe((status, [error]) {
        _subscribed = status == RealtimeSubscribeStatus.subscribed;
        if (!_subscribed) {
          _failClosed();
        } else {
          _onConnectionChanged?.call(true);
        }
        if (_subscribed && _pendingMode != null) {
          unawaited(_track(_pendingMode!));
        }
      });
  }

  void _failClosed() {
    _subscribed = false;
    _onPeerModeChanged?.call(null);
    _onConnectionChanged?.call(false);
  }

  void _syncPeerMode() {
    final channel = _channel;
    if (channel == null) return;
    final expectedPeerPresenceId = _expectedPeerPresenceId;
    if (expectedPeerPresenceId == null) {
      _failClosed();
      return;
    }
    final entries = <ConsultationPresenceEntry>[];
    for (final state in channel.presenceState()) {
      for (final presence in state.presences) {
        entries.add(ConsultationPresenceEntry(
          key: state.key,
          payload: Map<String, dynamic>.from(presence.payload),
        ));
      }
    }
    _onPeerModeChanged?.call(resolveExpectedPeerMode(
      entries: entries,
      expectedPeerPresenceId: expectedPeerPresenceId,
    ));
  }

  @override
  Future<void> publish(ConsultationMode mode) async {
    _pendingMode = mode;
    if (_subscribed) await _track(mode);
  }

  Future<void> _track(ConsultationMode mode) async {
    try {
      final localPresenceId = _localPresenceId;
      if (localPresenceId == null) {
        _failClosed();
        return;
      }
      await _channel?.track(consultationPresencePayload(
        authenticatedPresenceId: localPresenceId,
        mode: mode,
        updatedAt: DateTime.now(),
      ));
    } catch (_) {
      _failClosed();
    }
  }

  @override
  Future<void> untrack() async {
    _pendingMode = null;
    if (_subscribed) {
      try {
        await _channel?.untrack();
      } catch (_) {
        _failClosed();
      }
    }
  }

  @override
  Future<void> dispose() async {
    final channel = _channel;
    _channel = null;
    _subscribed = false;
    _pendingMode = null;
    _localPresenceId = null;
    _expectedPeerPresenceId = null;
    if (channel != null) {
      try {
        await channel.untrack();
      } catch (_) {
        // Presence is optional UX state and must never block teardown.
      }
      try {
        await channel.unsubscribe();
      } catch (_) {
        // The transport is already locally disposed.
      }
    }
  }
}

class ConsultationSessionRegistry {
  final Set<ConsultationSessionController> _sessions = {};

  void add(ConsultationSessionController session) => _sessions.add(session);
  void remove(ConsultationSessionController session) =>
      _sessions.remove(session);

  void handleAppLifecycleState(AppLifecycleState state) {
    for (final session in List.of(_sessions)) {
      session.handleAppLifecycleState(state);
    }
  }

  Future<void> shutdownAll() async {
    final sessions = List<ConsultationSessionController>.of(_sessions);
    _sessions.clear();
    await Future.wait(sessions.map((session) => session.shutdown()));
  }
}

final consultationSessionRegistryProvider =
    Provider<ConsultationSessionRegistry>((ref) {
  return ConsultationSessionRegistry();
});

final consultationSessionProvider =
    ChangeNotifierProvider.family<ConsultationSessionController, int>(
        (ref, appointmentId) {
  final dio = ref.watch(dioProvider);
  final registry = ref.watch(consultationSessionRegistryProvider);
  final controller = ConsultationSessionController(
    appointmentId: appointmentId,
    loadParticipant: () => ref.read(userProvider.future),
    historyGateway: DioConsultationHistoryGateway(dio),
    socketFactory: const WebSocketConsultationChatSocketFactory(),
    socketAuth: CoordinatedWebSocketAuth(
      ref.watch(authSessionCoordinatorProvider),
    ),
    presence: SupabaseConsultationPresenceTransport(
      Supabase.instance.client,
    ),
    apiBaseUrl: dio.options.baseUrl,
  );
  registry.add(controller);
  ref.onDispose(() {
    registry.remove(controller);
    unawaited(controller.shutdown());
  });
  return controller;
});

class ConsultationSessionController extends ChangeNotifier {
  ConsultationSessionController({
    required this.appointmentId,
    required Future<User?> Function() loadParticipant,
    required ConsultationHistoryGateway historyGateway,
    required ConsultationChatSocketFactory socketFactory,
    required CoordinatedWebSocketAuth socketAuth,
    required ConsultationPresenceTransport presence,
    required String apiBaseUrl,
    Duration reconnectDelay = const Duration(seconds: 2),
  })  : _loadParticipant = loadParticipant,
        _historyGateway = historyGateway,
        _socketFactory = socketFactory,
        _socketAuth = socketAuth,
        _presence = presence,
        _apiBaseUrl = apiBaseUrl,
        _reconnectDelay = reconnectDelay;

  final int appointmentId;
  final Future<User?> Function() _loadParticipant;
  final ConsultationHistoryGateway _historyGateway;
  final ConsultationChatSocketFactory _socketFactory;
  final CoordinatedWebSocketAuth _socketAuth;
  final ConsultationPresenceTransport _presence;
  final String _apiBaseUrl;
  final Duration _reconnectDelay;

  final List<Map<String, dynamic>> _messages = [];
  List<Map<String, dynamic>> get messages => List.unmodifiable(_messages);

  bool isLoading = true;
  Object? initializationError;
  int? myUserId;
  String? myRole;
  String? nextCursor;
  bool hasMore = true;
  bool isLoadingMore = false;
  int unreadCount = 0;
  ConsultationMode? peerMode;
  ConsultationConnectionState connectionState =
      ConsultationConnectionState.unavailable;
  bool consultationHasStarted = false;
  bool isConsultationClosed = false;
  bool isMessageGracePeriod = false;
  DateTime? videoEndsAt;
  DateTime? messagesEndAt;

  Future<void>? _initialization;
  bool _liveRequested = false;
  bool _presenceConnected = false;
  bool _connectingPresence = false;
  String? _expectedPeerPresenceId;
  bool _connectingSocket = false;
  bool _disposed = false;
  Future<void>? _shutdownFuture;
  bool _foreground = true;
  bool _chatAttached = false;
  bool _chatVisible = false;
  bool _videoActive = false;
  bool _videoChatVisible = false;
  ConsultationMode? _desiredMode;
  ConsultationChatSocket? _socket;
  StreamSubscription<dynamic>? _socketSubscription;
  Timer? _reconnectTimer;
  Timer? _videoEndTimer;
  Timer? _messageEndTimer;
  int _socketGeneration = 0;

  bool get isChatAttached => _chatAttached;
  bool get isChatVisible => _chatVisible;
  bool get isVideoActive => _videoActive;
  bool get isVideoChatVisible => _videoChatVisible;
  bool get canSend =>
      _socket != null &&
      connectionState == ConsultationConnectionState.connected &&
      !isConsultationClosed;
  bool get canStartCall =>
      consultationHasStarted && !isMessageGracePeriod && !isConsultationClosed;
  String get peerParticipantLabel => myRole == 'doctor' ? 'Patient' : 'Doctor';
  String get peerPresenceLabel => peerMode?.label ?? 'Not currently active';

  Future<void> ensureStarted({required bool live}) async {
    if (_disposed) return;
    _liveRequested = _liveRequested || live;
    final inFlight = _initialization;
    if (inFlight != null) {
      await inFlight;
      if (_liveRequested) await _ensureLiveConnections();
      return;
    }
    final future = _initialize();
    _initialization = future;
    await future;
  }

  Future<void> _initialize() async {
    try {
      final user = await _loadParticipant();
      if (user == null) {
        throw StateError('Authenticated profile was unavailable.');
      }
      myUserId = int.tryParse(user.id);
      myRole = user.role;
      if (myUserId == null) {
        throw StateError('Authenticated participant identity was invalid.');
      }
      await _loadLatestHistory(replace: true);
      if (_liveRequested) await _ensureLiveConnections();
      initializationError = null;
    } catch (error) {
      initializationError = error;
    } finally {
      isLoading = false;
      _notify();
    }
  }

  Future<void> retry() async {
    if (_disposed) return;
    initializationError = null;
    isLoading = true;
    _initialization = null;
    _notify();
    await ensureStarted(live: _liveRequested);
  }

  Future<void> _ensureLiveConnections() async {
    if (_disposed || myUserId == null) return;
    if (!_presenceConnected && !_connectingPresence) {
      _connectingPresence = true;
      try {
        await _presence.connect(
          appointmentId: appointmentId,
          expectedPeerPresenceId: _expectedPeerPresenceId,
          onPeerModeChanged: (mode) {
            peerMode = mode;
            _notify();
          },
          onConnectionChanged: (connected) {
            if (!connected) peerMode = null;
            _notify();
          },
        );
        _presenceConnected = true;
        await _publishDesiredMode();
      } catch (_) {
        // A failed optional presence connection must remain retryable. It is
        // never consultation authority and cannot lock chat or video access.
        _presenceConnected = false;
        peerMode = null;
        _notify();
      } finally {
        _connectingPresence = false;
      }
    }
    await _connectSocket();
  }

  Future<void> _connectSocket() async {
    if (_disposed || _connectingSocket || _socket != null || myUserId == null) {
      return;
    }
    _connectingSocket = true;
    _reconnectTimer?.cancel();
    try {
      final accessToken = await _socketAuth.tokenForConnection();
      final socket = _socketFactory.connect(_socketUri());
      final generation = ++_socketGeneration;
      _socket = socket;
      socket.send(jsonEncode({'type': 'auth', 'token': accessToken}));
      connectionState = ConsultationConnectionState.connected;
      _notify();
      _socketSubscription = socket.stream.listen(
        _handleSocketData,
        onError: (_) => _handleSocketClosed(
          generation: generation,
          accessToken: accessToken,
        ),
        onDone: () => _handleSocketClosed(
          generation: generation,
          accessToken: accessToken,
        ),
        cancelOnError: true,
      );
    } catch (_) {
      connectionState = ConsultationConnectionState.unavailable;
      _scheduleReconnect();
      _notify();
    } finally {
      _connectingSocket = false;
    }
  }

  Uri _socketUri() {
    var base = _apiBaseUrl.endsWith('/')
        ? _apiBaseUrl.substring(0, _apiBaseUrl.length - 1)
        : _apiBaseUrl;
    if (base.startsWith('https://')) {
      base = base.replaceFirst('https://', 'wss://');
    } else if (base.startsWith('http://')) {
      base = base.replaceFirst('http://', 'ws://');
    }
    return Uri.parse('$base/api/v1/p2p/live/$appointmentId/$myUserId');
  }

  void _handleSocketData(dynamic data) {
    if (_disposed) return;
    final decoded = jsonDecode(data.toString());
    if (decoded is! Map) return;
    final message = Map<String, dynamic>.from(decoded);
    if (message['type'] == 'consultation_timing') {
      _applyConsultationTiming(message);
      return;
    }
    if (message['type'] == 'consultation_closed') {
      isConsultationClosed = true;
      isMessageGracePeriod = false;
      _setDesiredMode(null);
      return;
    }
    if (message['type'] == 'presence' || message['type'] == 'call_signal') {
      return;
    }
    _appendIncomingMessage(message);
  }

  void _appendIncomingMessage(Map<String, dynamic> message) {
    final id = message['id']?.toString();
    if (id != null && _messages.any((item) => item['id']?.toString() == id)) {
      return;
    }
    final optimisticIndex = _messages.indexWhere((item) =>
        item['isSending'] == true && item['content'] == message['content']);
    if (optimisticIndex >= 0) {
      _messages[optimisticIndex] = message;
    } else {
      _messages.insert(0, message);
      final isCallSignal =
          message['content']?.toString().contains('"type":"call_signal"') ==
              true;
      if (!isCallSignal &&
          message['sender_id']?.toString() != myUserId?.toString()) {
        if (!_chatVisible && !_videoChatVisible) unreadCount += 1;
        HapticFeedback.vibrate();
        SystemSound.play(SystemSoundType.click);
      }
    }
    _notify();
  }

  Future<void> _handleSocketClosed({
    required int generation,
    required String accessToken,
  }) async {
    if (_disposed || generation != _socketGeneration) return;
    _socketGeneration += 1;
    final closedSocket = _socket;
    _socket = null;
    await _socketSubscription?.cancel();
    _socketSubscription = null;
    final closeCode = closedSocket?.closeCode;
    if ({4403, 4404, 4409, 4410, 4423}.contains(closeCode)) {
      connectionState = ConsultationConnectionState.unavailable;
      isConsultationClosed = closeCode == 4410 || isConsultationClosed;
      _desiredMode = null;
      await _presence.untrack();
      _notify();
      return;
    }
    connectionState = ConsultationConnectionState.reconnecting;
    await _publishMode(ConsultationMode.reconnecting);
    _notify();

    if (closeCode == 4401) {
      try {
        final recovered = await _socketAuth.recoverOnce(
          closeCode: closeCode,
          rejectedAccessToken: accessToken,
        );
        if (recovered && !_disposed) {
          await _loadLatestHistory(replace: false);
          await _connectSocket();
          await _publishDesiredMode();
          return;
        }
      } on TransientSessionRefreshException {
        // Keep the session alive and retry later.
      } on TerminalSessionRefreshException {
        return;
      } on AuthSessionUnavailableException {
        return;
      }
    }
    _scheduleReconnect();
  }

  void _scheduleReconnect() {
    if (_disposed || !_liveRequested || _reconnectTimer?.isActive == true) {
      return;
    }
    _reconnectTimer = Timer(_reconnectDelay, () async {
      if (_disposed || !_foreground) return;
      try {
        await _loadLatestHistory(replace: false);
      } catch (_) {
        // A subsequent reconnect remains able to recover durable history.
      }
      await _connectSocket();
      if (_socket == null) _scheduleReconnect();
      await _publishDesiredMode();
    });
  }

  Future<void> _loadLatestHistory({required bool replace}) async {
    final page = await _historyGateway.fetchHistory(appointmentId);
    final newestFirst = page.messages.reversed.toList();
    if (replace) {
      _messages
        ..clear()
        ..addAll(newestFirst);
    } else {
      for (final message in newestFirst.reversed) {
        final id = message['id']?.toString();
        if (id == null ||
            !_messages.any((item) => item['id']?.toString() == id)) {
          _messages.insert(0, message);
        }
      }
    }
    nextCursor = page.nextCursor;
    hasMore = page.hasMore;
    _expectedPeerPresenceId ??= page.peerPresenceId;
    _notify();
  }

  Future<void> fetchMoreMessages() async {
    if (_disposed || isLoadingMore || !hasMore) return;
    isLoadingMore = true;
    _notify();
    try {
      final page = await _historyGateway.fetchHistory(
        appointmentId,
        cursor: nextCursor,
      );
      for (final message in page.messages.reversed) {
        final id = message['id']?.toString();
        if (id == null ||
            !_messages.any((item) => item['id']?.toString() == id)) {
          _messages.add(message);
        }
      }
      nextCursor = page.nextCursor;
      hasMore = page.hasMore;
    } catch (_) {
      hasMore = false;
    } finally {
      isLoadingMore = false;
      _notify();
    }
  }

  String addOptimisticMessage(String content) {
    final id = 'temp_${DateTime.now().microsecondsSinceEpoch}';
    _messages.insert(0, {
      'id': id,
      'sender_id': myUserId,
      'content': content,
      'isSending': true,
      'created_at': DateTime.now().toUtc().toIso8601String(),
    });
    _notify();
    return id;
  }

  void updateOptimisticMessage(String id, String content) {
    final index = _messages.indexWhere((message) => message['id'] == id);
    if (index < 0) return;
    _messages[index]['content'] = content;
    _notify();
  }

  void removeOptimisticMessage(String id) {
    _messages.removeWhere((message) => message['id'] == id);
    _notify();
  }

  bool sendText(String content, {String? optimisticId}) {
    final trimmed = content.trim();
    if (trimmed.isEmpty || !canSend) return false;
    optimisticId ??= addOptimisticMessage(trimmed);
    try {
      _socket!.send(trimmed);
      return true;
    } catch (_) {
      removeOptimisticMessage(optimisticId);
      connectionState = ConsultationConnectionState.unavailable;
      _notify();
      return false;
    }
  }

  void sendCallSignal(String media) {
    if (!canSend || myUserId == null) return;
    _socket!.send(jsonEncode({
      'type': 'call_signal',
      'media': media,
      'status': 'initiated',
      'user_id': myUserId,
    }));
  }

  void attachChatSurface() {
    _chatAttached = true;
    setChatSurfaceVisible(true);
  }

  void detachChatSurface() {
    _chatAttached = false;
    setChatSurfaceVisible(false);
  }

  void setChatSurfaceVisible(bool visible) {
    _chatVisible = visible;
    if (visible) markMessagesSeen();
    if (!_videoActive) {
      _setDesiredMode(visible ? ConsultationMode.chat : null);
    }
    _notify();
  }

  void setVideoChatVisible(bool visible) {
    _videoChatVisible = visible;
    if (visible) markMessagesSeen();
    _notify();
  }

  void markMessagesSeen() {
    if (unreadCount == 0) return;
    unreadCount = 0;
    _notify();
  }

  void beginVideoTransition() {
    _videoActive = true;
    _setDesiredMode(ConsultationMode.joiningVideo);
  }

  void localVideoJoined({required bool remotePresent}) {
    _videoActive = true;
    _setDesiredMode(
        remotePresent ? ConsultationMode.video : ConsultationMode.videoWaiting);
  }

  void remoteVideoJoined() {
    _videoActive = true;
    _setDesiredMode(ConsultationMode.video);
  }

  void remoteVideoLeft() {
    if (_videoActive) _setDesiredMode(ConsultationMode.videoWaiting);
  }

  void mediaReconnecting() {
    if (_videoActive) _setDesiredMode(ConsultationMode.reconnecting);
  }

  void mediaReconnected({required bool remotePresent}) {
    if (_videoActive) {
      localVideoJoined(remotePresent: remotePresent);
    }
  }

  void videoJoinFailed({required bool returningToChat}) {
    leaveVideo(returningToChat: returningToChat);
  }

  void leaveVideo({required bool returningToChat}) {
    _videoActive = false;
    _videoChatVisible = false;
    _setDesiredMode(
        returningToChat && _chatAttached ? ConsultationMode.chat : null);
  }

  void handleAppLifecycleState(AppLifecycleState state) {
    if (_disposed) return;
    if (state == AppLifecycleState.resumed) {
      _foreground = true;
      if (_liveRequested && _socket == null) unawaited(_connectSocket());
      unawaited(_publishDesiredMode());
      return;
    }
    if (state == AppLifecycleState.inactive ||
        state == AppLifecycleState.paused ||
        state == AppLifecycleState.detached ||
        state == AppLifecycleState.hidden) {
      _foreground = false;
      unawaited(_presence.untrack());
    }
  }

  void _setDesiredMode(ConsultationMode? mode) {
    _desiredMode = mode;
    if (_foreground && _presenceConnected) {
      if (mode == null) {
        unawaited(_presence.untrack());
      } else {
        unawaited(_presence.publish(mode));
      }
    }
    _notify();
  }

  Future<void> _publishDesiredMode() async {
    if (!_foreground || !_presenceConnected) return;
    final mode = _desiredMode;
    if (mode != null) await _presence.publish(mode);
  }

  Future<void> _publishMode(ConsultationMode mode) async {
    if (_foreground && _presenceConnected) await _presence.publish(mode);
  }

  void _applyConsultationTiming(Map<String, dynamic> message) {
    final nextVideoEnd =
        DateTime.parse(message['video_ends_at'] as String).toLocal();
    final nextMessagesEnd =
        DateTime.parse(message['messages_end_at'] as String).toLocal();
    consultationHasStarted = true;
    videoEndsAt = nextVideoEnd;
    messagesEndAt = nextMessagesEnd;
    _scheduleConsultationTiming(nextVideoEnd, nextMessagesEnd);
    _notify();
  }

  void _scheduleConsultationTiming(
    DateTime nextVideoEnd,
    DateTime nextMessagesEnd,
  ) {
    _videoEndTimer?.cancel();
    _messageEndTimer?.cancel();
    final now = DateTime.now();
    void startGracePeriod() {
      if (_disposed || isConsultationClosed) return;
      isMessageGracePeriod = true;
      _notify();
    }

    if (!now.isBefore(nextMessagesEnd)) {
      isConsultationClosed = true;
      isMessageGracePeriod = false;
      return;
    }
    if (!now.isBefore(nextVideoEnd)) {
      startGracePeriod();
    } else {
      _videoEndTimer = Timer(nextVideoEnd.difference(now), startGracePeriod);
    }
    _messageEndTimer = Timer(nextMessagesEnd.difference(now), () {
      if (_disposed) return;
      isConsultationClosed = true;
      isMessageGracePeriod = false;
      _setDesiredMode(null);
      unawaited(_closeSocket());
    });
  }

  Future<void> _closeSocket() async {
    _socketGeneration += 1;
    final socket = _socket;
    _socket = null;
    await _socketSubscription?.cancel();
    _socketSubscription = null;
    await socket?.close();
  }

  Future<void> shutdown() => _shutdownFuture ??= _performShutdown();

  Future<void> _performShutdown() async {
    _disposed = true;
    _reconnectTimer?.cancel();
    _videoEndTimer?.cancel();
    _messageEndTimer?.cancel();
    await _closeSocket();
    await _presence.dispose();
    _messages.clear();
    peerMode = null;
    unreadCount = 0;
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    unawaited(shutdown());
    super.dispose();
  }
}
