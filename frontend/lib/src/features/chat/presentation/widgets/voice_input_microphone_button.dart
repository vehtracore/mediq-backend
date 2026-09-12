import 'package:flutter/material.dart';

import '../../data/voice_input_capability.dart';
import '../voice_input_controller.dart';

class VoiceInputMicrophoneButton extends StatelessWidget {
  final String selectedLanguage;
  final VoiceInputPhase phase;
  final bool interactionEnabled;
  final VoidCallback onPressed;

  const VoiceInputMicrophoneButton({
    super.key,
    required this.selectedLanguage,
    required this.phase,
    required this.interactionEnabled,
    required this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
    final capability = aiLanguageCapabilityFor(selectedLanguage);
    final isRecording = phase == VoiceInputPhase.recording;
    return Semantics(
      button: true,
      label: isRecording
          ? 'Stop voice recording'
          : capability.voiceInputEnabled
              ? 'Start voice recording'
              : 'Voice input unavailable for $selectedLanguage',
      child: IconButton(
        tooltip: isRecording
            ? 'Stop recording'
            : capability.voiceInputEnabled
                ? 'Record voice message'
                : 'Voice input unavailable',
        onPressed: interactionEnabled ? onPressed : null,
        style: IconButton.styleFrom(
          backgroundColor: isRecording ? Colors.redAccent : Colors.transparent,
        ),
        icon: Icon(
          isRecording
              ? Icons.stop
              : capability.voiceInputEnabled
                  ? Icons.mic_none
                  : Icons.mic_off_outlined,
          color: isRecording
              ? Colors.white
              : capability.voiceInputEnabled
                  ? Theme.of(context).colorScheme.onSurfaceVariant
                  : Theme.of(context).disabledColor,
          size: 22,
        ),
      ),
    );
  }
}
