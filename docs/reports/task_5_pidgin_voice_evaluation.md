# Task 5 Nigerian Pidgin voice-input release evaluation

This is a pre-production evaluation specification, not an accuracy claim. Use
only consenting internal testers reading the synthetic phrases in
`task_5_pidgin_voice_corpus.csv`. Do not use patient recordings or production
medical audio.

## Deterministic procedure

1. Use a staging build and a non-production OpenAI project.
2. Test at least three Nigerian Pidgin speakers across two supported Android
   devices and one supported iPhone.
3. Record every phrase once in a quiet room and once with ordinary background
   noise. Include the marked natural pause without tapping Stop.
4. Copy the transcript from the editable composer before sending anything.
   Never press Send as part of this evaluation.
5. Compare the transcript to `expected_transcript`. Ignore only case,
   punctuation, and repeated whitespace. Do not normalize Pidgin to English.
6. Mark every `critical_tokens` item present, absent, or meaning-reversed. Record
   substitutions verbatim in the results sheet, but do not include a tester's
   unrelated health information.
7. Repeat one failed provider request using the visible Retry action and confirm
   only that explicit action creates a second request.

## Required release checks

- No recording ends at the marked natural pause.
- No transcript is automatically sent to AI.
- Negation, pregnancy status, allergy status, medicine name, dose, frequency,
  side/body part, duration, and numbers have zero meaning reversals.
- Code-switching remains code-switched rather than being translated into
  polished Standard English.
- Cancel creates no transcription and leaves pre-existing typed text unchanged.
- The evaluator records exact-match and critical-token results per phrase,
  device, speaker, and noise condition.

Pidgin voice input must remain easy to disable through the centralized
capability map if this evaluation is unacceptable. Product/clinical owners must
approve the acceptance threshold before release; endpoint success alone is not
evidence of medical transcription accuracy.

## Bookmarked, out-of-scope TTS findings

- Generated temporary TTS MP3 files are not explicitly cleaned up.
- Per-message audio players can overlap playback.
- Replaying an old response after changing the global language can route it
  through the newly selected TTS language/provider.

These findings were intentionally not changed in Task 5.
