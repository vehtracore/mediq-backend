import 'package:flutter_test/flutter_test.dart';
import 'package:mediq_app/src/features/notifications/navigation/notification_intent.dart';
import 'package:mediq_app/src/features/notifications/navigation/notification_navigation_coordinator.dart';

void main() {
  test('appointment, subscription, family and payout intents use stable routes',
      () {
    expect(
      NotificationIntent.fromData({
        'type': 'consultation_room_ready',
        'appointment_id': '42',
      })?.route,
      '/appointment/42',
    );
    expect(
      NotificationIntent.fromData({
        'type': 'consultation_time_proposed',
        'appointment_id': '42',
      }, role: 'patient')
          ?.route,
      '/patient_home?tab=schedule',
    );
    expect(
      NotificationIntent.fromData({
        'type': 'consultation_request',
        'appointment_id': '42',
      }, role: 'doctor')
          ?.route,
      '/doctor_home?tab=requests',
    );
    expect(
      NotificationIntent.fromData({
        'type': 'consultation_confirmed',
        'appointment_id': '42',
      }, role: 'doctor')
          ?.route,
      '/doctor_home?tab=schedule',
    );
    expect(
      NotificationIntent.fromData({'type': 'subscription_expired'})?.route,
      '/subscription',
    );
    expect(
      NotificationIntent.fromData({'type': 'family_joined'})?.route,
      '/family_dashboard',
    );
    expect(
      NotificationIntent.fromData({'type': 'payout_sent'})?.route,
      '/doctor_home',
    );
  });

  test('malformed and unknown notification data fails closed', () {
    expect(
      NotificationIntent.fromData({'type': 'consultation_confirmed'}),
      isNull,
    );
    expect(NotificationIntent.fromData({'type': 'unknown'}), isNull);
    expect(NotificationIntent.fromData(const {}), isNull);
  });

  test('pending tap waits for router and authenticated restoration', () {
    final coordinator = NotificationNavigationCoordinator();
    final navigated = <String>[];

    expect(
      coordinator.submit({
        'type': 'consultation_confirmed',
        'appointment_id': '9',
      }),
      isTrue,
    );
    expect(navigated, isEmpty);

    coordinator.attachNavigator(navigated.add);
    expect(navigated, isEmpty);

    coordinator.updateSessionReady(true);
    expect(navigated, ['/appointment/9']);
    expect(coordinator.pendingIntent, isNull);
  });

  test('pending doctor intent resolves after role restoration', () {
    final coordinator = NotificationNavigationCoordinator();
    final navigated = <String>[];
    coordinator.submit({
      'type': 'consultation_confirmed',
      'appointment_id': '9',
    });
    coordinator.attachNavigator(navigated.add);
    coordinator.updateSessionReady(true, role: 'doctor');
    expect(navigated, ['/doctor_home?tab=schedule']);
  });
}
