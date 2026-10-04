# MDQ+ AI Reform: Wave 1 Implementation

Implementation review: 2026-09-24. Scope: provider foundation and current live defects only. The pre-launch application retains its existing entitlements, consent, quotas, Vault data contracts, lab storage, and media privacy behavior. Assessment, RAG, search, citations, and new assessment UI are not part of this wave.

## 1. Final provider architecture

`ClinicalAIProvider` is the single clinical reasoning boundary. `AIGenerationRequest` carries a purpose (`standard`, `heavy`, `summary`, `lab`), domain history, text/media parts, output budget, and optional structured-output flag. `AIGenerationResult` carries text, normalized completion, and token counts. `AIProviderError` carries a normalized category and retryability. `AI_PROVIDER=gemini` selects the only implemented adapter. STT/TTS providers remain independent of this reasoning setting.

## 2. Gemini adapter

`GeminiAdapter` owns SDK configuration, credentials, current standard/heavy model IDs, purpose mapping, role conversion, token counting, image loading, inline PDF content, structured JSON configuration, finish-reason mapping, bounded calls, and provider exception normalization. Provider/model names appear only in internal operational logs. The existing prompts and output budgets remain in place.

## 3. Coupling removed

Chat, summary, and lab domain services call the provider contract rather than importing Gemini SDK objects. Flutter sends `patient` and `mdq_plus` history roles; the adapter maps them to Gemini's native `user` and `model` roles. The frontend no longer constructs Gemini history. No parallel provider stack or old-client negotiation was added.

## 4. Request lifecycle

Repository evidence showed a 90-second Flutter receive timeout while backend generation could continue, with the old per-user guard allowing no status/recovery path. A second Send then encountered the old active-request conflict. That timing explains the observed sequence; it does not prove which individual provider call was slow on the device. The old guard also had a 180-second TTL but no patient-visible operation state.

Chat now uses one request ID and a payload fingerprint, an atomic PostgreSQL claim, a 270-second server processing limit, a 300-second stale-claim lease, and a 10-minute result receipt committed in the same database transaction as quota usage. A transaction-scoped PostgreSQL advisory lock fences live workers through generation, including when the claim lease expires. Same-key active calls return `202`; committed same-key calls replay without generating or charging again; changed payloads and different-key active calls return typed `409` errors. Success, handled failure, provider failure, cancellation, and timeout clear the claim; process death releases the lock and permits takeover after lease expiry. A status endpoint lets Flutter recover a delayed answer. Flutter tracks idle, sending, processing, delayed, succeeded, failed, and cancelled states and disables ordinary Send while an operation remains active. Chat no longer depends on Redis or a process-local guard.

## 5. Voice failure

The repository recorder requests AAC-LC, M4A, mono, 16 kHz, 64 kbps. We could not inspect the failing device's actual bytes, so its exact 400 cause remains unproven. The client now waits for a finalized stable file, reads its header, and derives multipart extension/MIME from the container before upload or retry. The backend validates M4A/MP4 plus AAC (`mp4a`) with a real decoder, or WAV/PCM, and rejects incomplete, mislabeled, or unsupported media with safe specific errors. An actual encoded M4A/AAC fixture and generated WAV tests cover the contract. Languages are unchanged. The device sample and a physical-device retest remain required to confirm the observed failure is gone.

## 6. Image failure

Failure to fetch or decode the authenticated temporary image now raises a typed `media_processing_failed` error. The backend does not make a text-only generation call while claiming image analysis, does not commit chat/attachment quota, and still attempts temporary-media cleanup.

## 7. Vault summary

`POST /api/v1/vault/ai-summary/save`, explicit save, consent, entitlement, source versioning, ownership, idempotency, summary persistence, and usage commit are unchanged. Summary token counting and generation now use the provider contract. A provider `quota_exhausted` category remains distinguishable internally from a database persistence error, while patient errors remain vendor-neutral. The latest observed live Save failed on Gemini heavy-model quota before persistence; this wave does not change billing or claim that a quota-limited deployment can now save.

## 8. Lab, PDF, and image paths

Lab analysis uses provider purpose `lab` with its existing prompt, paid gate, stored record, and response schema. PDF validation (8 MB, 1-10 pages, no encryption), request-scoped bytes, and heavy quota remain; the adapter builds the provider PDF payload. Images retain authenticated temporary Cloudinary handling and the heavy attachment count. The Flutter hidden lab follow-up prompt remains for the next interaction reform, but its chat request now shares delayed-operation recovery.

## 9. Evaluation baseline

`backend/tests/fixtures/ai_wave1_scenarios.json` records current observed behavior separately from desired requirements for informational questions, simple/complex/heavy symptoms, image, PDF, lab, Vault summary, max-token repair, provider quota, provider timeout, and voice upload. Known defects are not asserted as golden outcomes.

## 10. Verification

Full backend suite: 320 passed, 2 skipped, 26 subtests passed (started before the final focused assertions were added). Final focused Wave 1 backend suite: 14 passed. Full Flutter suite: 153 passed (started before the final two controller assertions were added). Final focused Flutter chat/voice suites: 35 passed. Changed-file `dart analyze`: no issues. `git diff --check`: passed. Full-project `flutter analyze --no-pub` was attempted but remained idle for several minutes and was stopped; it is not counted as a pass. Existing deprecation warnings remain in the backend suite.

## 11. Migration

Apply `backend/migrations/add_ai_chat_request_receipts.sql` before deploying the new chat endpoints. It creates short-lived receipt storage with a unique patient/request digest and expiry index. The periodic backend cleanup deletes expired receipts. Existing Vault/lab tables are not changed.

Apply `backend/migrations/add_ai_chat_claims.sql` after the receipt migration. Its patient primary key ensures one durable in-flight claim per patient. It contains only request digests, payload fingerprints, ownership tokens, and lease expiry, not clinical content.

## 12. Configuration

`AI_PROVIDER` defaults to `gemini`; unsupported values fail validation. Current `GEMINI_API_KEY`, `GEMINI_STANDARD_MODEL`, and `GEMINI_HEAVY_MODEL` remain. Startup validates the configured adapter's declared capabilities. Chat requires PostgreSQL; `AI_CHAT_LOCAL_OPERATIONS` is no longer used. Redis remains optional for existing unrelated cache/rate-limit paths. A real API key and adequate model quota are still required for live generation and Save.

## 13. Files changed

- Backend provider: `app/services/ai_provider.py`, `gemini_adapter.py`, `ai_service.py`, `ai_summary_service.py`.
- Backend lifecycle/API: `app/services/ai_chat_operation.py`, `app/models/ai_chat_claim.py`, `app/models/ai_chat_receipt.py`, `app/api/v1/chat.py`, `app/api/v1/vault.py`, `app/main.py`, claim and receipt migrations.
- Voice: `app/services/voice_transcription.py`, Flutter `voice_input_service.dart`, encoded fixture and tests.
- Flutter chat: `ai_chat_controller.dart` and controller tests.
- Backend tests: updated chat, PDF, Vault, voice, safe-error suites plus `test_ai_wave1.py` and evaluation fixture.

## 14. Real-device acceptance

- Apply both chat migrations; verify the deployed PostgreSQL transaction pooler permits the bounded transaction-scoped lock and has capacity for concurrent chat operations. Redis is not required for chat.
- Send a slow chat request, let the client HTTP request time out, and confirm the UI stays active, polls, and displays the original result once. Verify a second Send is disabled until terminal status, and quota increments once.
- Retry the same request ID and confirm one answer/charge; reuse it with edited content and confirm typed conflict.
- Record voice on the affected Android device and inspect actual container, codec, sample rate, channels, multipart filename/MIME, and finalization. Submit and Retry the same finalized recording in English and Pidgin; confirm a transcript enters the composer without auto-send. Attach the failed-device sample if the 400 persists.
- Test image fetch failure and verify no analysis claim, no attachment charge, and media cleanup. Test valid image and PDF paths.
- Test Exit & Save with sufficient configured provider quota; verify the summary appears in Vault and same-key retry does not duplicate it. Quota exhaustion should fail before any summary record is persisted.

## 15. Next-wave blockers

No architecture blocker to beginning the next implementation wave is known from repository tests. Deployment acceptance is gated by both chat migrations, PostgreSQL pooler verification, sufficient Gemini quota, and physical-device verification of the voice failure. The exact failing-device audio bytes were unavailable, so voice root cause must remain open until that check. The hidden lab follow-up prompt is intentionally left for the interaction reform.

## 16. Redis dependency review (2026-09-24)

The initial Wave 1 chat guard used Redis for a per-patient active key, same-key status, and a short result marker, with a process-local fallback. That made Redis mandatory for multi-worker correctness, even though PostgreSQL already held the durable success receipt and quota transaction.

PostgreSQL now owns both stages. An atomic insert into `ai_chat_claims` publishes the in-flight request across workers; its patient primary key prevents a second active claim. A committed receipt is checked before and again after claim/lock acquisition, closing the completion race. `pg_try_advisory_xact_lock` is held on the existing request database transaction while provider work runs. A stale claim can change owner only when that lock is free, and the old owner is rechecked before generation. Immediately before the answer and quota commit, the owner is checked again under a claim-row lock, fencing a worker whose database connection failed during generation. A committed receipt and quota update remain atomic. A worker crash rolls back/releases the transaction lock; after the lease, a new worker may take over. Transaction-level rather than session-level locking is deliberate because the current Supabase URL uses the port 6543 transaction pooler. [Supabase's connection-mode documentation](https://supabase.com/docs/guides/database/connecting-to-postgres) warns that session state does not survive transaction pooling; [PostgreSQL's lock documentation](https://www.postgresql.org/docs/current/explicit-locking.html) defines transaction-scoped advisory lock release.

Verification: 96 affected backend tests passed, including four tests against a disposable local PostgreSQL instance. The PostgreSQL tests execute the claim migration and use separate database connections to prove single-claim concurrency, payload conflict, live-worker fencing past lease expiry, crash recovery, old-owner fencing, and committed-result replay with one quota increment. PostgreSQL transaction capacity and any deployed idle-in-transaction timeout must be verified in staging; the request already held a database session during generation, but the new correctness lock requires that transaction to remain valid. A database connection failure during an external provider call can cause a later retry to make another physical provider call; only one result can become authoritative and charge quota. Neither Redis nor PostgreSQL alone can guarantee exactly one external call across a crash after the provider responds but before the result commits without provider-side idempotency. Redis is no longer a production prerequisite for chat.
