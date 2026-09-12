class NotificationIntent {
  const NotificationIntent(this.route);

  final String route;

  static NotificationIntent? fromData(Map<String, dynamic> data) {
    final type = data['type']?.toString();
    if (type == null || type.isEmpty) return null;

    const appointmentTypes = {
      'consultation_request',
      'consultation_payment_confirmed',
      'consultation_assigned',
      'consultation_confirmed',
      'consultation_cancelled',
      'consultation_room_ready',
      'consultation_completed',
      'prescription_added',
      'referral_created',
      'consultation_missed',
      // Accepted during the rolling client upgrade window.
      'vip_request_received',
      'schedule_confirmed',
      'schedule_cancelled',
      'consultation_room_open',
      'consultation_complete',
      'appointment_booked',
    };
    if (appointmentTypes.contains(type)) {
      final id = int.tryParse(data['appointment_id']?.toString() ?? '');
      return id != null && id > 0
          ? NotificationIntent('/appointment/$id')
          : null;
    }

    const subscriptionTypes = {
      'subscription_activated',
      'subscription_payment_failed',
      'subscription_cancelled',
      'subscription_expired',
      'subscription_successful',
    };
    if (subscriptionTypes.contains(type)) {
      return const NotificationIntent('/subscription');
    }

    if (type == 'family_member_joined' || type == 'family_joined') {
      return const NotificationIntent('/family_dashboard');
    }
    if (type == 'payout_sent') {
      return const NotificationIntent('/doctor_home');
    }
    return null;
  }
}
