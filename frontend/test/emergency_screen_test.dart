import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:geolocator/geolocator.dart';
import 'package:mediq_app/src/features/emergency/data/emergency_api.dart';
import 'package:mediq_app/src/features/emergency/data/emergency_location_service.dart';
import 'package:mediq_app/src/features/emergency/presentation/emergency_screen.dart';
import 'package:mediq_app/src/features/profile/presentation/settings_screen.dart';

Position get _position => Position(
      longitude: 3.3792,
      latitude: 6.5244,
      timestamp: DateTime.fromMillisecondsSinceEpoch(0, isUtc: true),
      accuracy: 2,
      altitude: 0,
      altitudeAccuracy: 0,
      heading: 0,
      headingAccuracy: 0,
      speed: 0,
      speedAccuracy: 0,
    );

class _FakeEmergencyApi extends EmergencyApi {
  NearbySearchResult searchResult;
  bool rejectAlert;
  int searchCalls = 0;
  int alertCalls = 0;
  final requestIds = <String>[];

  _FakeEmergencyApi({
    this.searchResult = const NearbySearchResult(
      status: NearbySearchStatus.success,
      services: [
        NearbyService(
          name: 'Nearby Hospital',
          phoneNumber: '112',
          category: 'hospital',
        ),
      ],
    ),
    this.rejectAlert = false,
  }) : super(Dio());

  @override
  Future<NearbySearchResult> searchNearby({
    required double latitude,
    required double longitude,
  }) async {
    searchCalls += 1;
    return searchResult;
  }

  @override
  Future<void> requestNextOfKinAlert({
    required double latitude,
    required double longitude,
    required String requestId,
    String? address,
  }) async {
    alertCalls += 1;
    requestIds.add(requestId);
    if (rejectAlert) throw StateError('simulated rejection');
  }
}

class _FakeLocationService extends EmergencyLocationService {
  final List<Object> positionResults;
  Future<String?> addressFuture;
  final requestedTimeouts = <Duration>[];
  final LocationPermission checkedPermission;
  final LocationPermission requestedPermission;
  int permissionRequests = 0;
  int settingsOpens = 0;

  _FakeLocationService({
    List<Object>? positionResults,
    Future<String?>? addressFuture,
    this.checkedPermission = LocationPermission.always,
    this.requestedPermission = LocationPermission.always,
  })  : positionResults = positionResults ?? [_position],
        addressFuture = addressFuture ?? Future<String?>.value('Test Area');

  @override
  Future<bool> isServiceEnabled() async => true;

  @override
  Future<LocationPermission> checkPermission() async => checkedPermission;

  @override
  Future<LocationPermission> requestPermission() async {
    permissionRequests += 1;
    return requestedPermission;
  }

  @override
  Future<bool> openAppSettings() async {
    settingsOpens += 1;
    return true;
  }

  @override
  Future<Position> currentPosition({
    required LocationAccuracy accuracy,
    required Duration timeLimit,
  }) async {
    requestedTimeouts.add(timeLimit);
    final result = positionResults.removeAt(0);
    if (result is Exception) throw result;
    return result as Position;
  }

  @override
  Future<String?> resolveAddress(Position position) => addressFuture;
}

Widget _app({
  required _FakeEmergencyApi api,
  required _FakeLocationService location,
  String? requestId = 'activation-123456',
}) {
  return ProviderScope(
    overrides: [
      emergencyApiProvider.overrideWithValue(api),
      emergencyLocationProvider.overrideWithValue(location),
    ],
    child: MaterialApp(
      home: EmergencyScreen(emergencyRequestId: requestId),
    ),
  );
}

void main() {
  testWidgets('one Emergency activation starts search and NOK branches once',
      (tester) async {
    final api = _FakeEmergencyApi();
    final location = _FakeLocationService();

    await tester.pumpWidget(_app(api: api, location: location));
    await tester.pumpAndSettle();

    expect(api.searchCalls, 1);
    expect(api.alertCalls, 1);
    expect(api.requestIds, ['activation-123456']);
    expect(find.text('Nearby services found'), findsOneWidget);
    expect(find.byIcon(Icons.local_hospital), findsOneWidget);

    // Rebuilding the same route preserves State and cannot create another send.
    await tester.pumpWidget(_app(api: api, location: location));
    await tester.pumpAndSettle();
    expect(api.alertCalls, 1);
  });

  testWidgets('search failure does not cancel the eligible NOK branch',
      (tester) async {
    final api = _FakeEmergencyApi(
      searchResult: const NearbySearchResult.unavailable(),
    );

    await tester.pumpWidget(
      _app(api: api, location: _FakeLocationService()),
    );
    await tester.pumpAndSettle();

    expect(api.searchCalls, 1);
    expect(api.alertCalls, 1);
    expect(
      find.text('Nearby search unavailable. Showing emergency contacts.'),
      findsOneWidget,
    );
    expect(find.textContaining('simulated'), findsNothing);
  });

  testWidgets('genuine zero result shows the 5 km fallback explanation',
      (tester) async {
    final api = _FakeEmergencyApi(
      searchResult: const NearbySearchResult(
        status: NearbySearchStatus.empty,
        services: [],
      ),
    );

    await tester.pumpWidget(
      _app(api: api, location: _FakeLocationService()),
    );
    await tester.pumpAndSettle();

    expect(
      find.text(
        'No nearby services found within 5 km. Showing emergency contacts.',
      ),
      findsOneWidget,
    );
    expect(find.text('Local Emergency'), findsOneWidget);
  });

  testWidgets('SMS rejection does not cancel nearby results', (tester) async {
    final api = _FakeEmergencyApi(rejectAlert: true);

    await tester.pumpWidget(
      _app(api: api, location: _FakeLocationService()),
    );
    await tester.pumpAndSettle();

    expect(api.alertCalls, 1);
    expect(api.searchCalls, 1);
    expect(find.text('Nearby Hospital'), findsOneWidget);
  });

  testWidgets('Retry performs one search and does not resend NOK',
      (tester) async {
    final api = _FakeEmergencyApi(
      searchResult: const NearbySearchResult.unavailable(),
    );

    await tester.pumpWidget(
      _app(api: api, location: _FakeLocationService()),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('Retry'));
    await tester.pumpAndSettle();

    expect(api.searchCalls, 2);
    expect(api.alertCalls, 1);
  });

  testWidgets('reverse geocoding does not delay nearby search', (tester) async {
    final address = Completer<String?>();
    final api = _FakeEmergencyApi();

    await tester.pumpWidget(
      _app(
        api: api,
        location: _FakeLocationService(addressFuture: address.future),
      ),
    );
    await tester.pump();
    await tester.pump();

    expect(api.searchCalls, 1);
    expect(api.alertCalls, 0);

    address.complete('Resolved Area');
    await tester.pumpAndSettle();
    expect(api.alertCalls, 1);
  });

  testWidgets('first timeout uses a bounded second attempt', (tester) async {
    final location = _FakeLocationService(
      positionResults: [TimeoutException('first'), _position],
    );
    final api = _FakeEmergencyApi();

    await tester.pumpWidget(_app(api: api, location: location));
    await tester.pumpAndSettle();

    expect(
      location.requestedTimeouts,
      [const Duration(seconds: 15), const Duration(seconds: 10)],
    );
    expect(api.searchCalls, 1);
    expect(api.alertCalls, 1);
  });

  testWidgets('two location failures stop loading and show static contacts',
      (tester) async {
    final location = _FakeLocationService(
      positionResults: [TimeoutException('first'), TimeoutException('second')],
    );
    final api = _FakeEmergencyApi();

    await tester.pumpWidget(_app(api: api, location: location));
    await tester.pumpAndSettle();

    expect(api.searchCalls, 0);
    expect(api.alertCalls, 0);
    expect(
      find.text('Location unavailable. Showing emergency contacts.'),
      findsOneWidget,
    );
    expect(find.text('Local Emergency'), findsOneWidget);
  });

  testWidgets('passive screen opening without activation ID never sends NOK',
      (tester) async {
    final api = _FakeEmergencyApi();

    await tester.pumpWidget(
      _app(api: api, location: _FakeLocationService(), requestId: null),
    );
    await tester.pumpAndSettle();

    expect(api.searchCalls, 1);
    expect(api.alertCalls, 0);
  });

  testWidgets('denied location permission remains on Emergency',
      (tester) async {
    final api = _FakeEmergencyApi();
    final location = _FakeLocationService(
      checkedPermission: LocationPermission.denied,
      requestedPermission: LocationPermission.denied,
    );

    await tester.pumpWidget(_app(api: api, location: location));
    await tester.pumpAndSettle();

    expect(find.text('Emergency'), findsOneWidget);
    expect(find.textContaining('Location permission denied'), findsOneWidget);
    expect(location.permissionRequests, 1);
    expect(api.searchCalls, 0);
  });

  testWidgets('permanent location denial waits for explicit Settings action',
      (tester) async {
    final location = _FakeLocationService(
      checkedPermission: LocationPermission.deniedForever,
    );

    await tester.pumpWidget(
      _app(api: _FakeEmergencyApi(), location: location),
    );
    await tester.pumpAndSettle();

    expect(find.text('Emergency'), findsOneWidget);
    expect(find.text('Open app settings'), findsOneWidget);
    expect(location.settingsOpens, 0);

    await tester.tap(find.text('Open app settings'));
    await tester.pump();
    expect(location.settingsOpens, 1);
  });

  testWidgets('nearby result card is tappable without narrow-width overflow',
      (tester) async {
    tester.view.physicalSize = const Size(320, 640);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      _app(api: _FakeEmergencyApi(), location: _FakeLocationService()),
    );
    await tester.pumpAndSettle();

    final card = find.byKey(
      const ValueKey('emergency-service-card-Nearby Hospital'),
    );
    expect(card, findsOneWidget);
    expect(tester.widget<InkWell>(card).onTap, isNotNull);
    expect(tester.takeException(), isNull);
  });

  test(
      'Settings consent copy describes automatic identity and location sharing',
      () {
    expect(emergencySmsConsentCopy, contains('tapping Emergency'));
    expect(emergencySmsConsentCopy, contains('automatically send your name'));
    expect(emergencySmsConsentCopy, contains('location/address'));
    expect(emergencySmsConsentCopy, contains('Next of Kin'));
  });
}
