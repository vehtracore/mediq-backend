import 'package:dio/dio.dart';

import '../api/app_exception.dart';

class UIErrorFormatter {
  static String getMessage(dynamic error) {
    if (error is AppException) {
      return error.message;
    }

    if (error is DioException && error.error is AppException) {
      return (error.error as AppException).message;
    }

    if (error is String) {
      return error;
    }

    return 'An unexpected error occurred. Please try again.';
  }
}
