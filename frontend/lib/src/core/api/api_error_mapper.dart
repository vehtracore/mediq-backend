import 'package:dio/dio.dart';

class ApiErrorMapper {
  static const _genericMessage = 'Something went wrong. Please try again.';
  static const _serverMessage =
      'Our servers are currently experiencing issues. Please try again later.';
  static const _networkMessage =
      'Check your internet connection and try again.';

  static final RegExp _unsafeDetailPattern = RegExp(
    r'<html|traceback|sql|exception:',
    caseSensitive: false,
  );

  static String getSecureErrorMessage(dynamic error) {
    if (error is! DioException) {
      return _genericMessage;
    }

    switch (error.type) {
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.sendTimeout:
      case DioExceptionType.receiveTimeout:
      case DioExceptionType.connectionError:
        return _networkMessage;
      case DioExceptionType.badResponse:
        return _messageForBadResponse(error);
      case DioExceptionType.cancel:
      case DioExceptionType.badCertificate:
      case DioExceptionType.unknown:
        return _genericMessage;
    }
  }

  static String _messageForBadResponse(DioException error) {
    final statusCode = error.response?.statusCode;
    final detail = _extractSafeDetail(error.response?.data);

    switch (statusCode) {
      case 400:
        return detail ?? 'Invalid request. Please try again.';
      case 403:
        return detail ?? 'You do not have permission to perform this action.';
      case 404:
        return detail ?? 'Resource not found.';
      case 422:
        return detail ?? 'Please check your input and try again.';
      case 500:
      case 502:
      case 503:
        return _serverMessage;
      default:
        if (statusCode != null && statusCode >= 500) {
          return _serverMessage;
        }
        return detail ?? _genericMessage;
    }
  }

  static String? _extractSafeDetail(dynamic data) {
    if (data is! Map) {
      return null;
    }

    final detail = data['detail'];
    if (detail is! String) {
      return null;
    }

    final trimmedDetail = detail.trim();
    if (trimmedDetail.isEmpty ||
        _unsafeDetailPattern.hasMatch(trimmedDetail)) {
      return null;
    }

    return trimmedDetail;
  }
}
