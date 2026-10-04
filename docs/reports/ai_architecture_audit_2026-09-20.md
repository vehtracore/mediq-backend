# MDQ+ AI System - Pre-Architecture Reform Audit

Date of audit: 2026-09-20  
Repository inspected: current working tree under `C:\Users\HP\Desktop\mediq_app`  
Scope: read-only technical/product audit of current AI behavior. No application source, prompts, migrations, configuration, models, or tests were changed.

## 1. Executive summary

MDQ+ currently has a single general patient AI chat implementation that is branded in the UI as an "AI Symptom Checker", but the backend does not maintain a structured symptom-assessment state machine. Ordinary text, image, PDF, saved-summary continuation, and lab-result follow-up all converge into `POST /api/v1/chat/analyze` or `POST /api/v1/chat/analyze-document`, then into `app.services.ai_service.get_medical_response`.

The current model architecture is tightly coupled to Gemini for chat, image/PDF, summaries, and lab analysis. It has a light/heavy Gemini model split controlled by Gemini-specific environment variables. Speech-to-text and English TTS use OpenAI. Local-language TTS uses YarnGPT. There is no provider-neutral abstraction for chat/model execution.

Save to Health Vault is still open. The code path is backend-owned and materially stronger than an older client-generated-summary design, but the current runtime can still fail if the deployed database does not contain the exact schema expected by `backend/app/models/vault.py` and `backend/app/api/v1/vault.py`. The strongest evidence-based root-cause candidates are schema drift around `ai_chat_summaries.updated_at`, `ai_chat_summaries.save_request_fingerprint`, and `ai_summary_save_idempotency`, plus entitlement mismatch and provider/summary generation failure. Runtime logs and one failing DB inspection are required to prove the exact cause.

No RAG, vector database, embeddings, clinical guideline corpus, web search, citation system, or source verification system exists for patient AI behavior. The current "knowledge" system is provider model knowledge plus prompt instructions and recent/history context.

## 2. Current user-facing AI flows

### Home-card entry

- Route/screen: `AiSymptomCheckerCard` in `frontend/lib/src/features/patient_dashboard/patient_home_screen.dart`; tap calls `context.pushNamed('aiChat')`.
- Destination: `/ai-chat`, route name `aiChat`, builder returns `AiChatScreen` in `frontend/lib/src/core/router/app_router.dart`.
- Controller/state: `AiChatController` via `aiChatControllerProvider`.
- User-visible copy: "AI Symptom Checker", "Describe your symptoms & get instant advice."
- Backend endpoint: none until chat action.
- Plan restrictions: no entry gate on home card.
- Persistence: no persistence until paid user explicitly uses Exit & Save.

### AI conversation screen

- Route/screen: `AiChatScreen` at `/ai-chat`; also reachable through `/chat` when `appointmentId == null`.
- Controller/state: `AiChatController` holds in-memory `messages`, loading state, rolling memory, staged image/PDF state, and optional continuation source.
- Backend endpoints:
  - Consent: `GET /api/v1/ai/consent/status`, `POST /api/v1/ai/consent`.
  - Text/image chat: `POST /api/v1/chat/analyze`.
  - PDF chat: `POST /api/v1/chat/analyze-document`.
  - Temporary image upload/delete: `POST /api/v1/chat/image`, `DELETE /api/v1/chat/image`.
  - Report AI response: `POST /api/v1/chat/report`.
- User-visible copy: "MDQ+", "Premium Mode"/"Free Mode", "AI support only - not a confirmed diagnosis.", welcome "I can help assess your symptoms."
- Plan restrictions: text and image/PDF chat are available to free users within quota; paid users get longer history, rolling memory, continuation, and save.
- Persistence: ephemeral unless saved through Health Vault. In-memory state is lost when the provider is disposed on route exit/process termination.

### Symptom-checker-labelled entry

- Present label: home card and backend route name `analyze_symptoms`.
- Current behavior: despite naming, code routes to a general health companion prompt. There is no explicit structured symptom checker workflow, no assessment readiness decision, and no structured clinical case state.

### Saved AI summary / Health Vault

- Route/screen: `VaultScreen` in `frontend/lib/src/features/vault/presentation/vault_screen.dart`.
- Repository/state: `vaultHistoryProvider` and `VaultRepository.getVaultHistory`.
- Backend endpoint: `GET /api/v1/vault/history`.
- Response type: list of `VaultHistoryResponse`, discriminated by `type` of `ai_summary` or `consultation`.
- User sees: `AISummaryCard` with "AI Health Summary", date, topic, Markdown-rendered details, menu actions.
- Plan restrictions: summaries remain visible for free/downgraded users; continuation is disabled unless paid.
- Persistence: AI summaries read from `ai_chat_summaries`; consultation records read from `consultation_records`.

### Continue with AI

- Entry: `AISummaryCard` menu item "Continue with AI".
- Frontend route: pushes `aiChat` with `sourceSummaryId` and `sourceSummaryUpdatedAt`.
- Chat request fields: `source_summary_id`, `source_summary_updated_at` for analyze; `source_summary_id`, `source_updated_at` for save.
- Backend: `chat._get_owned_source_summary` fetches owned summary and passes `summary_text` as historical context.
- Plan restrictions: frontend requires premium/family via `canContinueAi`; backend rejects non-paid entitlement.
- Persistence: continuation does not mutate source until Exit & Save succeeds.

### Image upload

- Entry: chat attachment menu "Upload Photo".
- Frontend: `ImageUploadService.pickAndUploadTemporaryAiImage`, then `AiChatController.sendMessage`.
- Backend endpoints: `POST /api/v1/chat/image` stores short-lived Cloudinary authenticated image; `POST /api/v1/chat/analyze` sends `image_public_id`, `image_url`, `image_format`.
- Request payload: JSON with `message`, `history`, `language`, optional memory fields, `image_url`, `image_public_id`, `image_format`.
- Response type: `ChatResponse { response, usage_notice?, memory_summary? }`.
- User sees: staged image preview and Markdown AI answer.
- Persistence: temporary image is deleted in backend `finally` and also best-effort from frontend cleanup. The chat message preview retains the URL in memory only.

### PDF upload

- Entry: chat attachment menu "Upload PDF".
- Frontend: `AiPdfAttachment` selected by picker, sent as multipart to `POST /api/v1/chat/analyze-document`.
- Request payload: multipart `file`, `message`, JSON-encoded `history`, `language`, optional memory and continuation fields.
- Response type: same `ChatResponse`.
- User sees: PDF filename chip and Markdown AI answer.
- Persistence: PDF bytes are request-scoped; frontend does not retain PDF bytes in chat state.

### Voice input

- Entry: microphone button in `AiChatScreen`.
- Frontend: `VoiceInputController`, `DioVoiceTranscriptionApi`.
- Backend endpoint: `POST /api/v1/voice/transcribe`.
- Request payload: multipart `file`, `language`, `request_identifier`.
- Response type: `{ transcript, language, status }`.
- User sees: transcript inserted into composer; the app does not auto-send.
- Plan restrictions: English and Nigerian Pidgin enabled; Yoruba/Hausa/Igbo typed only. STT has separate monthly quota and still requires AI consent/AI eligibility.
- Persistence: temporary audio files are deleted best-effort by frontend temp store; backend closes `UploadFile` and does not persist.

### Voice output

- Entry: per-AI-message speaker button.
- Backend endpoint: `POST /api/v1/voice/speak`.
- Request payload: `{ text, language }`.
- Response type: raw MP3 bytes.
- User sees: playback controls only.
- Persistence: frontend caches generated MP3 in temporary directory by language/text hash.

### AI urinalysis

- Entry: chat attachment menu "Scan Urine Test Strip".
- Frontend: paid gate in `AiChatScreen`, then `/lab_scanner`, then `LabRepository.uploadLabImage`.
- Backend endpoint: `POST /api/v1/lab/analyze`.
- Response type: `LabAnalysisResponse` JSON with `status`, `lighting_score`, `readings`, `notes`, optional `record_id`.
- User sees: scan result UI, then `sendLabResult` adds a lab-result bubble and sends hidden text to chat for explanation.
- Plan restrictions: premium/family only.
- Persistence: successful lab scans are stored in `lab_results` with authenticated Cloudinary media; the later chat explanation is ephemeral unless Exit & Save succeeds.

## 3. End-to-end request architecture

### Ordinary text message lifecycle

1. Flutter input: `AiChatScreen._sendMessage` reads composer text and selected language.
2. Frontend controller: `AiChatController.sendMessage` appends a user message with `isSending`, builds recent history, and creates `X-AI-Request-ID`.
3. API client: Dio posts to `/api/v1/chat/analyze`.
4. Backend route: `backend/app/api/v1/chat.py::analyze_symptoms` delegates to `_analyze_chat_request`.
5. Authentication: `deps.get_current_user`.
6. Consent: `require_active_ai_consent`.
7. Entitlement/quota:
   - paid entitlement via `has_active_paid_entitlement`;
   - global burst/cold cap;
   - free monthly text and attachment caps;
   - paid monthly fair-use and post-cap daily allowance.
8. Prompt/context construction: current age/chronic conditions, sanitized recent history, paid rolling memory, optional saved summary context.
9. Model/provider invocation: `ai_service.get_medical_response`.
10. Model selection: `requires_heavy_text_model` chooses `standard_model` or `heavy_model`.
11. Response processing: completion status inspected, optional max-token repair, memory update extracted, mode tags stripped.
12. Quota accounting: counters increment only after successful AI response.
13. API response: `ChatResponse(response, usage_notice, memory_summary)`.
14. Frontend rendering: `MarkdownBubble` for AI text; optional usage notice as system message.

### Image message

Image is first uploaded to `/api/v1/chat/image`, validated by `media_service.read_validated_upload`, stored as authenticated Cloudinary media under `mediq_ai_temp/{user_id}/{uuid}`, and returned as signed URL/public ID/format. Analyze then regenerates a fresh signed URL from the public ID. `ai_service` fetches the URL with `httpx`, opens it with Pillow, and appends the image plus an image-analysis instruction to the Gemini prompt.

Important caveat: if image fetch fails inside `ai_service`, the code logs a warning and continues without the image. That means an image-bearing request can degrade to text-only while still being treated as a heavy attachment in quota accounting.

### PDF message

`AiChatController` posts multipart to `/api/v1/chat/analyze-document`. `read_validated_ai_pdf` enforces 8 MB max, PDF header, parseability, non-encryption, and 1-10 pages. Bytes are appended inline as `{"mime_type": "application/pdf", "data": document_bytes}`. Provider failure does not fall back to text-only.

### Voice-transcribed message

Voice transcription is not a chat message by itself. The audio is recorded locally, sent to `/api/v1/voice/transcribe`, and the transcript is placed into the composer. The user must review/send it, and the normal chat quota is consumed only when the reviewed text is sent to `/api/v1/chat/analyze`.

### Continue from Vault

`VaultScreen` passes summary ID and updated timestamp into `AiChatScreen`. Analyze requests include `source_summary_id` and `source_summary_updated_at`. Backend checks paid entitlement, ownership, and exact updated timestamp, then injects `summary_text` as saved historical context.

### Exit & Save

Paid users see `Exit & Save`. `AiChatController.saveSummary` posts to `/api/v1/vault/ai-summary/save` with:

```json
{
  "turns": [{"role": "user|assistant", "text": "..."}],
  "source_summary_id": "... optional ...",
  "source_updated_at": "... optional ..."
}
```

The request includes `X-AI-Request-ID`. Backend checks entitlement/consent/idempotency, generates a bounded summary using Gemini heavy model, writes or updates `ai_chat_summaries`, writes `ai_summary_save_idempotency`, records one text-AI use, and returns `VaultHistoryResponse`.

## 4. Active prompt inventory

### Main health chat prompt

- File/function: `backend/app/services/ai_service.py::SYSTEM_INSTRUCTION`, formatted in `get_medical_response`.
- Used by: text, image, PDF, lab-result follow-up via `/api/v1/chat/analyze` and `/api/v1/chat/analyze-document`.
- Conditions: always included in main chat prompt.
- Dynamic values: `target_language`; user profile age/chronic conditions; recent history; paid rolling memory; older unsummarized turns; saved historical summary; raw user input.
- Expected output: free text, optional hidden `<memory_update>...</memory_update>`.
- Current behavioral effect: general empathetic health companion with language enforcement, Nigerian emergency protocol, and simple/complex/visual/emergency classification.
- Symptom assessment behavior:
  - Explicitly conducts structured symptom assessment: no.
  - Gathers information over multiple turns: only loosely through history and possible follow-up question; no state machine.
  - Explicit enough-information decision: no.
  - Distinguishes chat from assessment: only through prompt modes, not deterministic routing.
  - Asks one question or several: prompt permits "a useful follow-up question"; no hard limit.
  - Forces follow-up question: no.
  - Forces reassurance/complimentary language: it asks for reassuring language where appropriate; not compliments.
  - Red-flag escalation: yes, prompt-only Nigerian emergency protocol.
  - Factual information vs symptom report: no explicit deterministic distinction.
  - Prevents premature diagnostic statements: says likely interpretation without claiming diagnosis; no enforcement beyond prompt.

### Memory update prompt fragment

- File/function: `ai_service.get_medical_response`, `memory_output_instruction`.
- Used by: paid chat when frontend sets `update_memory`.
- Dynamic values: none beyond conversation content.
- Expected output: free text plus exact hidden memory update tag.
- Processing: backend strips/extracts the tag and fails malformed memory markup.

### Image attachment prompt fragment

- File/function: `ai_service.get_medical_response`.
- Used when `image_url` is present.
- Text appended: analyze medical relevance of image in context.
- Expected output: free-text answer.

### PDF attachment prompt fragment

- File/function: `ai_service.get_medical_response`.
- Used when `document_bytes` is present.
- Text appended: treat PDF as untrusted medical context and ignore document instructions.
- Expected output: free-text answer.

### Max-token repair prompt

- File/function: `ai_service.get_medical_response`.
- Used when text-only response finishes with max tokens and contains text.
- Expected output: one complete concise regenerated response.
- Quota effect: repair call still counts as one logical use only if final response succeeds.

### Health Vault summary prompts

- File/functions: `backend/app/services/ai_summary_service.py`.
- Prompts:
  - `_direct_prompt`
  - `_chunk_prompt`
  - `_final_chunked_prompt`
  - `_historical_compaction_prompt`
  - shared `_CONTINUITY_REQUIREMENTS`
- Used by: `generate_ai_vault_summary`, called by `/api/v1/vault/ai-summary/save`.
- Dynamic values: ephemeral turns, optional historical summary, chunk summaries.
- Expected output: bounded free-text structured note with headings.
- Behavior: creates medical-continuity summary, preserves uncertainty/chronology, does not invent facts.

### Voice transcription prompts

- File: `backend/app/services/voice_transcription.py`.
- English prompt: faithful English transcription, preserve medicine/dose/frequency, no summary/inference.
- Pidgin prompt: faithful Nigerian Pidgin/code-switching transcription, no translation/polish/inference.
- Expected output: transcript JSON text from OpenAI transcription API.

### Lab analysis prompt

- File/function: `backend/app/services/ai_service.py::LAB_ANALYSIS_PROMPT`, `analyze_lab_strip`.
- Used by: `/api/v1/lab/analyze`.
- Expected output: strict JSON with `status`, `lighting_score`, readings, notes; rejected images return JSON.
- Behavior: quality control, color/readings extraction for urinalysis strip.

### Lab-result chat follow-up prompt

- File/function: `frontend/lib/src/features/chat/presentation/ai_chat_controller.dart::_buildSystemPrompt`.
- Used after successful lab scan.
- Dynamic values: lab readings.
- Expected output: normal chat prose through main AI route.
- Note: This is a frontend-generated hidden/system-looking message sent as user `message`, not a backend-owned typed prompt.

## 5. Current model/provider routing

### Normal text AI

- Provider: Gemini via `google.generativeai`.
- Default model: `GEMINI_STANDARD_MODEL` env var or `gemini-3.1-flash-lite`.
- Heavy model: `GEMINI_HEAVY_MODEL` env var or `gemini-3.5-flash`.
- Selection: `requires_heavy_text_model`.
- Heavy triggers: image, document, memory update, long text > 1200 chars, and keyword markers such as chest pain, difficulty breathing, suicidal, pregnancy/newborn, interactions, chronic disease, lab/test results.
- Timeout: not explicitly configured in code for Gemini calls.
- Retry/rewrite: one max-token repair for text-only nonempty max-token responses; no provider retry.
- Limits: input token limit 4000; output 500 standard, 800 image/PDF.
- Structured output: not used for main chat.

### Heavy reasoning

Not a separate product mode. It is the same prompt/model call routed to the heavy Gemini model by heuristic.

### Image/PDF

- Provider: Gemini heavy model.
- Image ingestion: Cloudinary signed URL fetched by backend, Pillow image appended.
- PDF ingestion: inline PDF bytes appended to Gemini contents.
- Output: same free-text `ChatResponse`.

### Speech-to-text

- Provider: OpenAI.
- Default model: `OPENAI_STT_MODEL` env var or `gpt-transcribe`.
- Retry: disabled (`max_retries=0`); Flutter retry is explicit user action.
- Timeout: OpenAI client timeout 75s; Flutter receive timeout 90s.
- Structured output: provider JSON response, backend returns transcript string.

### Text-to-speech

- English provider/model: OpenAI `tts-1`, voice `alloy`.
- Local-language provider: YarnGPT voices for Igbo/Hausa/Yoruba/Pidgin.
- Timeout: YarnGPT `httpx.AsyncClient(timeout=60.0)`.
- Output: MP3 bytes.

### Summarisation/persistence

- Provider: Gemini heavy model.
- Token limits: chunk input 2400, final input 3200; chunk output 320, final output 800.
- Provider call limits: max 18 total Gemini calls, max 6 generation calls.

### Coupling assessment

- Provider-neutral components already present: `MedicalAIResponse`, `GenerationInspection`, quota services, request guards, save summary request/response schemas.
- Gemini-specific components: global `standard_model`/`heavy_model`, Gemini env var names, Gemini history roles (`user`/`model`), token counting, inline PDF format, logs and exception names, lab prompt execution.
- Areas needing abstraction later: chat model client, multimodal payload format, token counting, completion inspection, structured output handling, model routing policy, provider-specific safety finish mapping.
- Frontend/API leakage: API contracts use Gemini history role `"model"` and frontend method `_recentGeminiHistory`; not normally patient-visible but it embeds provider format in Flutter. Backend logs include model names.

## 6. Conversation/context architecture

- Frontend in-memory state: `AiChatState.messages`, `_conversationMemory`, `_unsummarizedTurns`, staged image/PDF/voice states.
- Backend conversation state: stateless per request except saved summaries, user quota counters, consent fields, and lab/STT records.
- Prior turns used:
  - Free: frontend sends 4 messages max; backend also enforces passed history max 4.
  - Paid/family: frontend sends 10 messages max; backend caps at `MAX_HISTORY_MESSAGES` 10.
- Rolling memory: paid only; after 7 unsummarized turns, frontend asks backend for hidden memory update; backend returns `memory_summary`; frontend stores it in memory only.
- Saved-summary context: paid continuation injects `AIChatSummary.summary_text` as historical data.
- Patient profile context: age from `dob`; chronic conditions only. Allergies, medications, surgeries, blood type are not included in the main AI prompt.
- App backgrounding: voice recording is interrupted outside resumed state; chat text state remains if widget/provider remains alive.
- Process termination: unsaved chat and rolling memory are lost.
- Logout/login: in-memory chat state is lost.
- Continue from Vault: starts a new ephemeral chat seeded by saved summary context.
- Structured clinical state: none found for presenting concern, onset, duration, severity, associated symptoms, negatives, risk factors, red flags, questions asked, missing information, or readiness.

## 7. Save to Vault audit and evidence-based failure analysis

### Current intended path

1. User taps back/exit in `AiChatScreen`.
2. Paid user sees `AiChatExitDialog` with "Exit & Save".
3. `AiChatController.saveSummary` posts `turns` to `/api/v1/vault/ai-summary/save` with `X-AI-Request-ID`.
4. Backend route: `backend/app/api/v1/vault.py::save_ai_summary`.
5. Authentication: `deps.get_current_user`.
6. Entitlement: `has_active_paid_entitlement`.
7. Consent: `require_active_ai_consent`.
8. Idempotency:
   - request digest from `X-AI-Request-ID`;
   - payload fingerprint from turns/source;
   - in-memory/Redis result cache;
   - durable `ai_summary_save_idempotency` table.
9. Rate/concurrency: `enforce_ai_save_rate_limit`, `acquire_ai_request_lease`.
10. Quota availability: `enforce_ai_text_usage_available`.
11. Summary generation: `generate_ai_vault_summary`.
12. DB write:
   - new summary: insert `AIChatSummary(id, patient_id, topic, summary_text, source, save_request_fingerprint, created_at, updated_at)`;
   - continuation: update existing `summary_text` and monotonic `updated_at`;
   - insert `AISummarySaveIdempotency`.
13. Metering: `record_successful_ai_text_usage`.
14. Response: `VaultHistoryResponse`.
15. Frontend: success snackbar, invalidate vault history, pop chat screen.
16. Vault retrieval: `GET /api/v1/vault/history` queries `AIChatSummary` and `ConsultationRecord`, sorts newest first, renders `AISummaryCard`.

### Schema/code expectations

Runtime code expects:

- Table `ai_chat_summaries` with columns: `id UUID`, `patient_id`, `topic`, `summary_text`, `source`, `save_request_fingerprint`, `doctor_review_status`, `reviewed_by_doctor_id`, `reviewed_at`, `created_at`, `updated_at`.
- Table `ai_summary_save_idempotency` with unique `(patient_id, request_key_digest)`.
- `users` quota fields for monthly/burst/rolling chat usage.

Migrations present:

- `backend/migrations/add_ai_summary_updated_at.sql`: adds/backfills/not-null `updated_at`.
- `backend/migrations/add_ai_summary_save_request_fingerprint.sql`: adds `save_request_fingerprint` and creates `ai_summary_save_idempotency`.
- `backend/migrations/add_ai_summary_review_metadata.sql`: adds source/review metadata.

Startup patch in `backend/app/main.py` adds source/review metadata, but in the inspected code it does not add `updated_at`, `save_request_fingerprint`, or `ai_summary_save_idempotency`.

### Error paths and frontend behavior

- Non-paid: 403, frontend shows mapped message and chat remains.
- Missing consent: 403.
- Stale continuation version: 409, chat remains.
- Too-large conversation: 413.
- Summary generation failure: 503, "The summary could not be saved. Please try again."
- Integrity or unknown persistence failure: 503, same safe message.
- Frontend preserves active conversation on save failure and reuses same idempotency request ID on retry unless new message content is added.

### Root-cause candidates ranked by code evidence

1. Deployed DB schema missing one or more of `ai_chat_summaries.updated_at`, `ai_chat_summaries.save_request_fingerprint`, or `ai_summary_save_idempotency`.
   Evidence: current route/model requires them; startup DDL does not add all of them; user reports physical app save still fails despite previous migrations. This would fail at insert/update/query/idempotency and surface as generic save failure.

2. Migration provenance for `ai_chat_summaries` table is incomplete or environment-specific.
   Evidence: this repo contains alter migrations for `ai_chat_summaries`, but no create-table migration was found in `backend/migrations`. If production/staging table was created manually or by older ORM behavior, its shape may differ.

3. Frontend/backend entitlement mismatch.
   Evidence: frontend `canSave` uses `controller.hasPaidContinuity` based on `subscriptionTier`; backend uses `has_active_paid_entitlement(current_user)`. An expired paid-looking local profile could show "Exit & Save" while backend rejects.

4. Summary-generation provider failure.
   Evidence: save depends on Gemini heavy model and token counting. Missing/invalid `GEMINI_API_KEY`, provider safety/max-token/malformed/empty output, or input limit failure returns save failure. Needs logs to distinguish from DB failure.

5. Continuation timestamp equality/precision mismatch.
   Evidence: continuation update filters `AIChatSummary.updated_at == payload.source_updated_at` after comparing aware UTC values. Precision/timezone serialization differences could create 409 or stale-save failure for continued summaries only.

### Runtime evidence needed from one failing Save

Capture:

- HTTP status and response body for `POST /api/v1/vault/ai-summary/save`.
- Backend logs around `[Vault] AI summary save failed`, `[Vault] AI summary generation failed`, or SQLAlchemy exception class.
- DB introspection:
  - `\d ai_chat_summaries`
  - `\d ai_summary_save_idempotency`
  - presence/nullability/defaults of `updated_at`, `save_request_fingerprint`, `source`, review columns.
- Current user row: `plan`, `subscription_expiry`, `ai_consent_granted_at`, `ai_consent_withdrawn_at`, chat quota fields.
- Whether the request is new save or continuation and exact `source_updated_at`.

Do not fix during this audit.

## 8. Multimodal architecture

- Image validation: upload must be JPG/PNG/WebP, max 5 MB, content signature checked.
- Image storage: temporary authenticated Cloudinary object under `mediq_ai_temp`; signed URL TTL 15 minutes; stale cleanup deletes old images after 2 hours.
- Image durability: AI chat images are intended temporary only; lab images are durable when lab scan succeeds.
- PDF validation: max 8 MB, 1-10 pages, unencrypted, parseable, `%PDF-` header.
- PDF storage: not persisted; bytes held per request and sent inline to provider.
- Cleanup: PDF `UploadFile` is not explicitly closed in chat route after read; no app storage copy is created. Image deletion is backend `finally` plus frontend best-effort.
- Quota: image and PDF share `monthly_chat_image_count` and paid heavy usage limit. Lab scans share paid heavy usage with chat attachments via `monthly_heavy_ai_usage`.
- Routing: image/PDF force heavy model.
- Output: same prose `ChatResponse`; no structured multimodal response.

## 9. Knowledge/RAG/search status

No patient AI RAG or evidence system was found.

Absent:

- vector database;
- embeddings;
- document retrieval;
- clinical guideline corpus;
- web-search fallback;
- search grounding;
- citations/source objects;
- URL validation for generated sources;
- knowledge-base abstraction.

Existing infrastructure that could later support retrieval but is not RAG today:

- PostgreSQL/SQLAlchemy;
- `google-api-python-client` dependency, currently unrelated to patient AI retrieval;
- `httpx` for network calls;
- PDF parser `pypdf`;
- saved AI summaries as historical context, not evidence retrieval.

## 10. Clinical safety architecture

Deterministic backend rules:

- AI consent required before AI chat/lab/voice transcription.
- Quota/cold-cap throttles high-frequency AI use.
- Attachment size/type/page validation.
- PDF/image prompt-injection fencing.
- Completion validation rejects blocked/missing/max-token image/PDF responses.
- STT validation preserves faithful transcription and refuses unsupported voice languages.
- Lab local image quality preflight and failed-scan guard.

Prompt-only rules:

- Nigerian emergency protocol with 112/199.
- Non-diagnosis phrasing and uncertainty.
- Red-flag escalation guidance.
- Language instructions.
- Lab JSON prompt.
- Save summary instruction not to invent facts.

Provider-native safety:

- Gemini finish reasons mapped to safe categories including safety/blocklist/prohibited content/SPII/image safety.
- OpenAI transcription behavior is provider-native after local validation.

Frontend-only disclaimers:

- "AI support only - not a confirmed diagnosis."
- Consent dialog states MDQ+ AI is not diagnosis, prescription, or emergency service.

Not present:

- Deterministic red-flag classifier/router.
- Deterministic self-harm pathway beyond prompt/provider behavior.
- Deterministic pediatric/pregnancy pathway beyond heavy-routing markers and prompt.
- Structured malformed-output handling for main prose beyond completion/memory tag validation.

## 11. Quotas/cost-control behavior

- Free text chat: 12 successful messages per calendar month.
- Free attachments: 2 successful image/PDF analyses per month, sharing `monthly_chat_image_count`.
- Paid Premium: 300 standard messages per month, warning at 250, then 5 priority messages per rolling 24 hours.
- Family: 250 standard messages per member per month, warning at 200, then 5 priority messages per rolling 24 hours.
- Paid heavy attachment/lab: 10 combined AI attachment and lab interpretations per month.
- Global cold cap: after 15 messages in 15 minutes, user is blocked for 15 minutes.
- One AI use: successful chat response increments chat count; successful image/PDF increments chat count and image count; successful Save increments one text-AI use; successful STT increments STT quota but not chat quota; successful TTS increments audio character counters.
- Reservation/commit:
  - Chat: checks before provider, commits counters after successful AI response.
  - Save: checks before generation, commits summary/idempotency and usage in one DB commit.
  - STT: reserves monthly STT slot before provider call, finalizes/refunds afterward.
  - TTS: reserves audio quota before provider call, refunds on failure.
- Retry/rewrite accounting: chat max-token repair still consumes one logical use only after successful repaired answer; failed repair consumes none.
- Save operations: metered as one text-AI use on success.

## 12. Privacy/provider-data exposure

Data sent to Gemini chat:

- User message.
- Recent conversation history: 4 free or 10 paid messages.
- Paid rolling memory and older unsummarized turns when present.
- Saved summary text when continuing.
- Age and chronic conditions.
- Image bytes indirectly via signed Cloudinary URL fetched server-side and passed to Gemini.
- PDF bytes inline for document analysis.

Data sent to Gemini summary:

- All save payload turns, bounded by `MAX_TURNS`, `MAX_TURN_CHARS`, and `MAX_CONVERSATION_CHARS`.
- Optional historical saved summary.

Data sent to OpenAI:

- Voice audio bytes for STT.
- English TTS text for speech synthesis.

Data sent to YarnGPT:

- Local-language TTS text and selected voice.

Logging/telemetry:

- Backend logs include plan, model name, heavy/image/document booleans, token counts, finish categories, provider names for voice/TTS/STT, response length, and failure categories.
- Code avoids logging prompt/user content in inspected AI paths.
- `sentry-sdk` and `posthog_flutter` are dependencies; this audit did not find AI prompt/response logging calls to those tools in the inspected AI paths.

Temporary media:

- AI chat images: Cloudinary authenticated temporary assets; deleted after analysis or stale cleanup.
- PDF: request-scoped bytes, not persisted.
- Voice input: local temp `.m4a`, deleted by frontend after use/cancel/stale cleanup; backend closes upload.
- TTS: frontend temp MP3 cache.

## 13. User-facing internal/provider leaks

Confirmed user-facing or near-user-facing strings:

- Good: Flutter UI does not name Gemini, OpenAI, GPT, YarnGPT, or model names in ordinary AI chat screens.
- Consent text says "third-party AI provider" generically. This exposes the existence of a provider but not the vendor/model.
- `frontend/lib/src/core/api/api_error_mapper.dart` explicitly screens unsafe provider terms from backend errors.
- `VaultScreen` export/share subject uses "VehtraCore Health Vault Records", which appears inconsistent with the MDQ+ product identity and should be treated as a brand/internal leak.
- App bar shows "Premium Mode" and "Free Mode"; not provider leakage.

Internal frontend/backend coupling not normally patient-visible:

- `_recentGeminiHistory` name and comments mention Gemini in Flutter code.
- Backend comments/logs mention Gemini/OpenAI/YarnGPT/model names.
- API history role uses provider-specific `"model"` role.

## 14. Frontend response architecture

API response shapes:

- Chat: typed JSON `ChatResponse` with plain/Markdown-capable prose in `response`, optional `usage_notice`, optional `memory_summary`.
- PDF: same chat response over multipart endpoint.
- Image upload: JSON `{ url, public_id, format, expires_at }`.
- Vault history: typed JSON list `VaultHistoryResponse`.
- Lab: structured JSON readings.
- Voice STT: JSON transcript.
- TTS: binary MP3.

Rendering:

- Normal answer: `MarkdownBubble`.
- Warning/error: system message bubble/snackbar using `ApiErrorMapper`.
- Attachments: image preview via `Image.network`; PDF filename chip; lab result bubble.
- Save controls: exit dialog only, no persistent save button inside chat.
- Quota messages: backend detail mapped to system message/snackbar; successful fair-use warnings shown as `usage_notice`.
- Continuation: banner warns earlier saved information may be out of date.

What would break if backend assessment output changed to structured JSON:

- `AiChatController` expects `response.data['response']` to be a string.
- `MarkdownBubble` expects text.
- Save turns serialize displayed message strings.
- Tests assert prose response handling.
- A structured assessment renderer and API type change would be needed; returning JSON inside `response` would render raw JSON as Markdown text.

## 15. Existing test coverage

Backend coverage found:

- `test_ai_chat_quality.py`: prompt quality, max-token repair, completion failures, memory parsing, free/paid context bounds, continuation entitlement/context, quota behavior for repair.
- `test_ai_pdf.py`: PDF validation, inline Gemini PDF compatibility, provider failure behavior, saved historical context length, image path, attachment counter.
- `test_ai_vault_continuation.py`: save/continue behavior, idempotency, stale conflicts, bounded summary generation, chunking, export labels, free user viewing/deleting saved summaries.
- `test_voice_transcription.py`: audio validation, prompts, capability gating, quota reservation/finalization/refunds, provider no-retry, upload closure, route auth/rate limits.
- `test_sensitive_media_privacy.py` and `test_lab_scan_guard.py`: relevant media/lab safeguards.

Frontend coverage found:

- `ai_chat_controller_test.dart`: active session preservation, failed save retaining chat, safe error contract, continued save payload, stale conflict, all turns saved, idempotency retry, PDF endpoint usage.
- `ai_entitlement_ui_test.dart`: free exit no Save, paid Exit & Save, free locked continuation, paid continuation.
- `ai_error_surface_test.dart`: provider/internal error redaction.
- `mdq_ai_branding_test.dart`: MDQ+ branding.
- `voice_input_test.dart`: voice capability map, microphone states, transcription behavior, cleanup, Dio multipart request, quota messages.

Important gaps:

- No end-to-end test against a real migrated database for Save to Vault.
- No test proving deployed schema contains `updated_at`, `save_request_fingerprint`, and `ai_summary_save_idempotency`.
- No deterministic clinical risk router tests because no router exists.
- No structured symptom-assessment state tests because no state exists.
- No tests for provider abstraction or provider replacement.
- No golden/integration test proving Health Vault shows a newly saved summary after real backend save.
- No tests for image fetch failure degrading to text-only while consuming attachment quota.
- No source/citation/RAG tests because feature does not exist.

## 16. Current-vs-target gap matrix

| Future component | Classification | Evidence |
|---|---|---|
| Intent/risk router | NEW COMPONENT | Current route name is symptom-oriented but no deterministic router exists. |
| Casual conversation mode | REFACTOR | Current prompt supports general health chat but not as explicit mode. |
| Symptom-assessment controller | NEW COMPONENT | No structured assessment controller/state. |
| Structured clinical case state | NEW COMPONENT | No fields for onset, severity, negatives, readiness, etc. |
| Red-flag path | REFACTOR | Prompt-only emergency mode and heavy markers exist; no deterministic path. |
| Information-question path | NEW COMPONENT | No explicit factual-question route. |
| Provider abstraction | REFACTOR | Provider-neutral dataclasses exist but execution is Gemini-specific. |
| Light-model capability | REFACTOR | Standard Gemini model exists; policy is hard-coded. |
| Heavy-model capability | REFACTOR | Heavy Gemini model exists; policy is hard-coded. |
| Multimodal capability | REFACTOR | Image/PDF/lab exist but are Gemini-specific and prose-only. |
| Curated RAG | NEW COMPONENT | None found. |
| Web-search fallback | NEW COMPONENT | None found. |
| Evidence/source objects | NEW COMPONENT | None found for patient AI. |
| Structured final assessment | NEW COMPONENT | Current output is prose. |
| Flutter assessment renderer | NEW COMPONENT | Current renderer expects Markdown/prose. |
| Persistence | REFACTOR | Vault summaries exist but Save is still failing in real testing. |
| Quotas | REFACTOR | Quotas exist but are per call/message, not assessment-session based. |
| Observability/evaluation | REFACTOR | Operational logs exist; no evaluation harness or clinical quality telemetry found. |

## 17. Confirmed technical constraints

- MDQ+ must remain the user-facing product identity.
- Current UI should not expose vendor/model/internal architecture names to patients.
- Do not connect AI to doctor consultation workflows unless behavior already exists; this audit found no AI-doctor handoff in the patient AI path.
- Free users do not get Save on Exit or Continue from Vault.
- Premium/Family persistence is intended behavior.
- Save to Vault remains open until verified on a real device/runtime DB.
- Chat frontend currently expects prose string responses.
- Backend chat/model code currently depends on Gemini SDK semantics.
- No RAG/search/evidence layer exists today.

## 18. Unknowns that require runtime evidence or product decision

Runtime evidence:

- Exact deployed DB schema for `ai_chat_summaries` and `ai_summary_save_idempotency`.
- Exact backend exception during one failing Save attempt.
- Whether failing device points at production/staging/local backend and which migration set that database has.
- Whether user profile shows paid locally while backend entitlement is expired/inactive.
- Whether Gemini summary generation is failing for actual conversation payloads.
- Whether startup DDL has permission to alter production tables.

Product decisions:

- Whether "AI Symptom Checker" should remain the entry label if future behavior includes casual chat and information questions.
- Whether "third-party AI provider" is acceptable in consent copy or should be phrased differently.
- How to count future multi-question assessments: per message/model call or per assessment.
- What clinical evidence sources are approved for future RAG/search.
- Which structured assessment fields and renderers are required for MDQ+.
- Whether provider/model details belong in any user-facing legal/policy surfaces.

## CONFIRMED

- Current patient AI is a general Gemini-backed chat with optional image/PDF, paid memory, and saved-summary continuation.
- Save to Vault is implemented as backend-generated summary persistence but remains unverified and plausibly blocked by schema/runtime drift.
- No structured clinical assessment state exists.
- No RAG/search/citation system exists.
- Free users cannot Save on Exit or Continue from Vault through current UI/backend gates.
- The ordinary UI does not expose Gemini/OpenAI/model names, though "VehtraCore" appears in Vault export sharing subject.

## NEEDS RUNTIME VERIFICATION

- Deployed DB columns/tables for AI summaries and idempotency.
- Backend log/error for one failing physical-device Save.
- Actual paid entitlement values for the failing user.
- Whether generated summary succeeds before persistence fails.
- Whether Vault retrieval would render a saved row if manually present with current schema.

## NEEDS PRODUCT DECISION

- Future intent/risk routing taxonomy.
- Structured symptom-assessment schema and renderer.
- RAG/search source policy.
- AI assessment quota semantics.
- Provider disclosure language in consent/legal docs versus ordinary UX.

## DO NOT CHANGE YET

- Do not implement provider abstraction.
- Do not add RAG or web search.
- Do not change prompts/models.
- Do not fix Save to Vault in this task.
- Do not create migrations or alter schema in this task.
- Do not redesign UI or quotas in this task.
