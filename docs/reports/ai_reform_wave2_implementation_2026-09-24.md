# MDQ+ AI Reform: Wave 2 Implementation

Implementation review: 2026-09-24 (verification continued 2026-09-25). This is the pre-launch interaction core only. It does not add a full assessment controller, assessment persistence or result, RAG, web search, or new assessment quotas.

## 1. Typed interaction contract

`InteractionResponse` has `request_id`, `interaction_id`, `operation_status=SUCCEEDED`, `mode`, `result_kind`, a discriminated `result`, optional `usage_notice`, `memory_summary`, and `safe_error`. The only modes are `CONVERSATION`, `ASSESSMENT`, and `URGENT`. The implemented result kinds are `MESSAGE` (`text`), `ASSESSMENT_QUESTION` (`question`, `can_cancel`), and `URGENT` (`action`, `reason`, `emergency_number`). `ASSESSMENT_RESULT` is deliberately left for Wave 3. No provider, model, router confidence, or reason code enters this response. In-flight `202` and status polling retain the Wave 1 operation envelope; failures retain safe `ApiError` responses.

## 2. Orchestrator and safety

`ai_orchestrator.run_interaction` owns deterministic safety, routing, mode dispatch, and the result shape. The FastAPI route retains authentication dependencies, consent, entitlement, media validation, quota availability, operation claim, accounting, and the atomic receipt commit. `ai_safety` has a versioned evaluation (`urgent_override`, flags, policy version) and a deliberately small set of high-confidence personal emergency patterns: severe chest pain, breathing crisis, severe bleeding, unresponsiveness/not breathing, and sudden stroke-like signs. A deterministic urgent flag bypasses the provider router and cannot be downgraded. Clinical policy review is still required before launch; this is not a general-purpose medical rules engine.

The new urgent action uses Nigeria's `112`, which the [Nigerian Communications Commission](https://ncc.gov.ng/media-centre/press-releases/press-release-emergency-communications-centres-launch-ncc) identifies as a toll-free emergency number for ambulance and other responders. Emergency escalation for severe chest pain with breathlessness is consistent with the [WHO heart-attack fact sheet](https://www.who.int/news-room/fact-sheets/detail/heart-attack). The UI presents the action first, a short reason, and a call control. It does not return a differential or expose internal flags.

## 3. Provider-assisted router

`RouterInput` carries bounded patient text, language, recent `patient`/`mdq_plus` turns, allowed profile context, optional verified lab context, an attachment with `PRESENT_UNPROCESSED` status, safety evaluation, and continuation intent. It carries no provider SDK object or native role. The existing `ClinicalAIProvider` gains a `router` purpose and structured JSON generation. `GeminiAdapter` owns native JSON configuration and parsing; `RouterDecision` validates mode, bounded confidence, reason IDs, presenting concern, safety signals, ambiguity, and an optional one-question candidate. Invalid JSON/schema becomes normalized `INVALID_STRUCTURED_OUTPUT`, never patient-facing raw text. No repair generation is used.

Fallbacks are deterministic urgent first; otherwise clearly personal symptoms become an Assessment clarification, ordinary information becomes Conversation, and ambiguous input receives one clarification. Router timeouts and provider quota failures do not independently charge patient quota. For image/PDF, routing includes the media itself; a media processing or structured-router failure propagates instead of pretending that an attachment was processed.

## 4. Mode behavior

Conversation keeps the Wave 1 provider abstraction and bounded history but now uses a direct information-answering instruction. It does not require a symptom interview, reassurance, or follow-up question. Existing emergency/non-diagnosis boundaries remain. Assessment returns one question, not an invitation to begin or a fake progress indicator. The router's candidate is shape-checked; a small, high-value fallback question is available for common concern wording. Urgent is backend-generated, action-first, and works even when provider routing is unavailable for a deterministic flag.

The temporary continuation is an `interaction_id` UUID held in Flutter memory and sent with the next answer, alongside the existing bounded conversation history. The backend uses it to recognize an Assessment continuation and avoid restarting the opening question. The patient can end this temporary continuation in the UI. It is **not** a durable or trusted assessment record; Wave 3 must replace this bridge with its persistent controller/state while preserving the Flutter `ASSESSMENT_QUESTION` result model.

## 5. Multimodal and lab

Image and PDF remain context, never clinical modes. The router receives actual media; a successful router call has processed that attachment, and Conversation generation may inspect it again. Existing temporary-image access/cleanup and PDF validation remain. Failed media does not produce a successful receipt or usage commit. Lab scan records and scanner behavior are unchanged. Flutter now sends `lab_result_id`, not hidden AI instructions. The backend verifies `LabResult.user_id`, requires usable saved raw data, supplies a bounded reading summary as untrusted provider-neutral context, and lets the router choose the mode. No cross-user scan can be read through chat.

## 6. Flutter, lifecycle, and quotas

Flutter decodes sealed `AiMessageResult`, `AiAssessmentQuestionResult`, and `AiUrgentResult` models. Message still uses Markdown/TTS/report controls; AssessmentQuestion appears in the conversation with the normal composer and an exit action; Urgent uses a distinct accessible error-colored panel and `tel:112` call button. The composer now invites a health question, not only symptoms. No provider name or internal routing term was added to the patient result UI. Existing generic third-party processing disclosure in the AI-consent dialog was left intact; legal/policy text was not changed.

Wave 1 PostgreSQL claims, payload fingerprints, 202 status, delayed polling, receipt replay, and same-transaction quota/result commit are unchanged. The receipt's JSON column stores the new typed result, so no schema change is required. A duplicate logical request replays that typed JSON without another generation or charge. Flutter still disables Send in sending/processing/delayed states and does not resubmit a delayed request. Existing message/attachment quota thresholds and paid/free history policy remain. Router and any answer-repair calls are internal to one patient-visible interaction; only success reaches the existing accounting block. Redis remains optional and is not a chat prerequisite.

## 7. Privacy and observability

Router history, patient text, lab summary, and profile fields are bounded. Logs record mode, confidence band, fallback state, request/interaction IDs, and normalized provider category, not patient text, clinical facts, raw router output, or model response. Reason codes remain backend-internal. The synthetic scenarios in `ai_wave2_scenarios.json` separate Wave 1 observed behavior from desired/forbidden mode, safety expectation, and question expectation; they are not real conversations.

## 8. Verification

- Focused Wave 2 backend suite: 20 passed, covering information, personal symptoms, urgent override, model safety-signal escalation, ambiguity, malformed output, timeout/quota fallback, attachment success/failure, lab ownership, continuation, and typed mode results.
- Final full backend suite: 340 passed, 6 skipped, 26 subtests passed. The skips include PostgreSQL claim integration tests that require a disposable local `TEST_POSTGRES_URL`.
- Focused Flutter chat/render suites: 25 passed. Final full Flutter suite: 161 passed.
- Changed-file `dart analyze`: no issues. Full-project `flutter analyze --no-pub`: 166 warnings/info findings across the existing app, not a clean pass. `git diff --check`: passed.
- PostgreSQL claim integration tests are skipped without a disposable local `TEST_POSTGRES_URL`; Wave 1 previously exercised these against local PostgreSQL. No live clinical provider or physical device was used in this wave.

## 9. Schema, configuration, and files

No Wave 2 migration or environment variable was added. Wave 1 claim/receipt migrations remain deployment prerequisites. The existing configured Gemini adapter adds the `router` purpose using the configured heavy model; no provider competition or Redis requirement was introduced.

Changed backend: `app/api/v1/chat.py`, `app/services/ai_interaction.py`, `ai_safety.py`, `ai_router.py`, `ai_orchestrator.py`, `ai_provider.py`, `gemini_adapter.py`, `ai_service.py`; tests in `test_ai_wave2.py`, updated Wave 1 chat/PDF/voice/claim tests, and `fixtures/ai_wave2_scenarios.json`. Changed Flutter: `data/ai_interaction.dart`, `presentation/ai_chat_controller.dart`, `ai_chat_screen.dart`, `widgets/ai_interaction_bubbles.dart`, and chat/render tests. Pre-existing unrelated dirty files were not intentionally changed.

## 10. Physical-device acceptance

1. Apply both Wave 1 PostgreSQL migrations. Send the same request on two backend workers, confirm one authoritative result, one quota charge, typed replay, changed-payload conflict, and delayed recovery after the Flutter receive timeout.
2. Ask the information, symptom, ambiguous, and urgent fixture questions in supported languages. Confirm one useful question for Assessment, no repeated introductory question on the next answer, no forced interview for information, and an action-first urgent panel whose `112` button opens the dialer.
3. Attach a valid/invalid image and PDF to information and symptom prompts. Confirm the media is genuinely processed or returns a safe error, with no successful charge on failure. Verify temporary-image cleanup.
4. Scan a urinalysis strip and open its chat follow-up. Verify the saved record is read only by its owner and Flutter sends a reference rather than a hidden prompt.
5. Test consent, Free/Premium/Family allowances, Vault summary save after mixed typed results, request cancellation/exit, screen-reader order, small-screen layout, and Android/iOS call handling.

## 11. Wave 3 boundary

No code-level blocker to beginning Wave 3 is known. Before release, clinical review must approve emergency patterns/action copy and the assessment question fallback, and supported-language urgent/clarification copy needs localization review. The temporary UUID-and-history continuation has no durable assessment state, step tracking, clinical synthesis, or final result; Wave 3 must replace it rather than extend it. Live provider, multi-worker staging, and physical-device acceptance remain open.
