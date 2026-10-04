class ApiConstants {
  static const bool isStaging = false;

  static const String prodBaseUrl = 'https://api.mdqplus.com';
  static const String stagingBaseUrl =
      'https://mediq-backend-1-r71p.onrender.com';

  static const String baseUrl = isStaging ? stagingBaseUrl : prodBaseUrl;

  static const String loginEndpoint = '/api/v1/auth/login';
  static const String signupEndpoint = '/api/v1/auth/signup';
}