import 'package:flutter/foundation.dart';

enum VoiceInputProvider { openAi }

@immutable
class AiLanguageCapability {
  final String displayName;
  final String apiValue;
  final bool typedInputEnabled;
  final bool voiceInputEnabled;
  final bool voiceOutputEnabled;
  final VoiceInputProvider? voiceInputProvider;

  const AiLanguageCapability({
    required this.displayName,
    required this.apiValue,
    this.typedInputEnabled = true,
    required this.voiceInputEnabled,
    this.voiceOutputEnabled = true,
    this.voiceInputProvider,
  }) : assert(voiceInputEnabled == (voiceInputProvider != null));
}

const aiLanguageCapabilities = <String, AiLanguageCapability>{
  'English': AiLanguageCapability(
    displayName: 'English',
    apiValue: 'english',
    voiceInputEnabled: true,
    voiceInputProvider: VoiceInputProvider.openAi,
  ),
  'Nigerian Pidgin': AiLanguageCapability(
    displayName: 'Nigerian Pidgin',
    apiValue: 'pidgin',
    voiceInputEnabled: true,
    voiceInputProvider: VoiceInputProvider.openAi,
  ),
  'Yoruba': AiLanguageCapability(
    displayName: 'Yoruba',
    apiValue: 'yoruba',
    voiceInputEnabled: false,
  ),
  'Hausa': AiLanguageCapability(
    displayName: 'Hausa',
    apiValue: 'hausa',
    voiceInputEnabled: false,
  ),
  'Igbo': AiLanguageCapability(
    displayName: 'Igbo',
    apiValue: 'igbo',
    voiceInputEnabled: false,
  ),
};

AiLanguageCapability aiLanguageCapabilityFor(String displayName) {
  return aiLanguageCapabilities[displayName] ??
      aiLanguageCapabilities['English']!;
}
