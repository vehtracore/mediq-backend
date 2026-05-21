class AppException implements Exception {
  final String message;
  final Object? originalException;

  AppException(this.message, {this.originalException});

  @override
  String toString() => message;
}
