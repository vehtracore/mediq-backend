class NotificationRecord {
  const NotificationRecord({
    required this.id,
    required this.type,
    required this.title,
    required this.body,
    required this.navigationData,
    required this.isRead,
    required this.createdAt,
  });

  final int id;
  final String? type;
  final String title;
  final String body;
  final Map<String, String> navigationData;
  final bool isRead;
  final DateTime createdAt;

  factory NotificationRecord.fromJson(Map<String, dynamic> json) {
    final rawNavigation = json['navigation_data'];
    return NotificationRecord(
      id: json['id'] as int,
      type: json['type']?.toString(),
      title: json['title']?.toString() ?? '',
      body: json['body']?.toString() ?? '',
      navigationData: rawNavigation is Map
          ? rawNavigation.map(
              (key, value) => MapEntry(key.toString(), value.toString()),
            )
          : const {},
      isRead: json['is_read'] == true,
      createdAt: DateTime.parse(json['created_at'].toString()).toLocal(),
    );
  }

  Map<String, String> get intentData => {
        if (type != null) 'type': type!,
        ...navigationData,
      };
}
