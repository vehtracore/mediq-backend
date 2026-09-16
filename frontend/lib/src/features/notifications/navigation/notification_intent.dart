class NotificationIntent {
  const NotificationIntent(this.route);

  final String route;

  static NotificationIntent? fromData(Map<String, dynamic> data,
      {String? role}) {
    final type = data['type']?.toString();
    if (type == null || type.isEmpty) return null;

    if (type == 'consultation_time_proposed' && role != 'doctor') {
      return const NotificationIntent('/patient_home?tab=schedule');
    }

    if (role == 'doctor') {
      const requestTypes = {'consultation_request', 'vip_request_received'};
      if (requestTypes.contains(type)) {
        return const NotificationIntent('/doctor_home?tab=requests');
      }
    }

    const appointmentTypes = {
      'consultation_request',
      'consultation_time_proposed',
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
      if (role == 'doctor') {
        return const NotificationIntent('/doctor_home?tab=schedule');
      }
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
