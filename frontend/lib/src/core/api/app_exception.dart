import 'api_error_mapper.dart';

class AppException implements Exception {
  final String message;
  final Object? originalException;
  final ApiFailure? failure;

  AppException(this.message, {this.originalException, this.failure});

  AppException.fromFailure(ApiFailure this.failure, {this.originalException})
      : message = failure.message;

  @override
  String toString() => message;
}
