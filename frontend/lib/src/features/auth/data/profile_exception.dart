class ProfileTemporaryException implements Exception {
  const ProfileTemporaryException(this.message, {this.cause});

  final String message;
  final Object? cause;

  @override
  String toString() => message;
}

class ProfileAuthoritativeException implements Exception {
  const ProfileAuthoritativeException(this.message, {this.cause});

  final String message;
  final Object? cause;

  @override
  String toString() => message;
}
