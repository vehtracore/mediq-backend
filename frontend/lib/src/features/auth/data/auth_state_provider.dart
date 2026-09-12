import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

final supabaseAuthProvider = StreamProvider<AuthState>((ref) {
  return Supabase.instance.client.auth.onAuthStateChange;
});

final authUserIdProvider = Provider<String?>((ref) {
  final authState = ref.watch(supabaseAuthProvider);
  if (authState.isLoading) return null;
  return authState.valueOrNull?.session?.user.id ??
      Supabase.instance.client.auth.currentSession?.user.id;
});
