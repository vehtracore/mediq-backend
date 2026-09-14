import 'package:dio/dio.dart';

import '../api/app_exception.dart';
import '../api/api_error_mapper.dart';

class UIErrorFormatter {
  static const _fallback = 'An unexpected error occurred. Please try again.';

  static String getMessage(dynamic error) {
    if (error is AppException) {
      if (error.failure?.shouldPresent == false) return '';
      return ApiErrorMapper.safeDisplayMessage(error.message);
    }
    if (error is DioException) {
      if (error.error is AppException) {
        final appError = error.error as AppException;
        if (appError.failure?.shouldPresent == false) return '';
        return ApiErrorMapper.safeDisplayMessage(appError.message);
      }
      return ApiErrorMapper.map(error).message;
    }
    return _fallback;
  }

  static bool shouldPresent(dynamic error) {
    if (error is AppException && error.failure != null) {
      return error.failure!.shouldPresent;
    }
    if (error is DioException) return ApiErrorMapper.map(error).shouldPresent;
    return true;
  }
}
