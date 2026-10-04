# MDQ+ AI Reform: Wave 3 Implementation

Implementation review: 2026-09-25. This wave replaces the temporary Assessment continuation with a backend-owned adaptive session. It does not add RAG, web search, automatic Vault saving, provider competition, or probability scoring.

## 1. Assessment persistence model

`ai_assessments` holds a patient-owned UUID session, status, concern, language, schema/state versions, readiness/reasons, originating and latest operation IDs, timestamps, 72-hour expiry, optional source Vault summary ID, latest typed response, final result, and a one-use accounting marker. `ai_assessment_facts` and `ai_assessment_questions` are child rows deleted with the session. The tables are migration-only at application startup. No assessment clinical state is stored in Redis or Health Vault.

## 2. Lifecycle/state machine

The implemented states are ACTIVE, READY, COMPLETED, URGENT, CANCELLED, ABANDONED, and reserved EXPIRED. A routed personal concern creates ACTIVE. A provider proposal plus domain checks yields one question or READY; a valid final result yields COMPLETED. A deterministic urgent flag, or a provider urgent proposal, yields URGENT and stops questioning. Cancellation and a clear topic switch end the current active path. Terminal states reject further answers. EXPIRED is represented by hard deletion rather than a retained clinical row.

## 3. Fact/provenance model

Facts carry controlled concept, value, ASSERTED/DENIED/UNCERTAIN/UNKNOWN status, USER_STATED/MODEL_INFERENCE/ATTACHMENT_DERIVED provenance, source turn, optional attachment ID, and a superseded-fact pointer. RETRIEVED_EVIDENCE is reserved in the migration but is not generated in Wave 3. User facts require an exact quote from the current patient message; a proposed denial additionally requires explicit negative wording. A bare yes/no answer is linked to the asked question. Unknown/refusal is recorded rather than demanded repeatedly. Inferences are retained for planning but excluded from the patient-history and final-result fact set. Contradictory patient statements remain in history and trigger clarification when material.

## 4. Question model

Questions persist concept, unique per-assessment semantic key, wording, ask/answer timestamps, answer turn, answer status, and text. The domain rejects known/previously asked concepts, identical wording, malformed/bundled proposals, and already answered information. It normally returns one question. The controlled vocabulary is intentionally practical and extensible, not a universal ontology.

## 5. Controller

`advance_assessment` owns transitions and is invoked through the existing PostgreSQL chat claim. Continuations skip the generic router, lock the owned assessment row, verify expected `state_version`, and commit the session and typed receipt together. The per-user PostgreSQL operation claim/advisory transaction lock fences multiple workers; the session row lock and version check fence stale devices. Same-key receipt replay avoids a second generation or charge. An invalid final proposal receives one repair attempt; repeated invalidity leaves READY with a retryable safe failure and no completed-use charge.

## 6. Question selection

The provider proposes structured facts, needs, questions, readiness, and safety signals. Domain ranking weights safety, next-step impact, differential value, uncertainty reduction, and burden in that order. Known and repeated needs are filtered; unresolved contradiction clarification takes precedence. A minimal onset fallback covers a bare concern if the proposal provides no useful question. This is not a fixed questionnaire; the synthetic fixture tests properties rather than an exact sequence.

## 7. Readiness

Readiness is a provider proposal constrained by reliable factual dimensions, unresolved high-safety needs, and unresolved contradictions. A sufficiently detailed opening report can proceed directly to READY and final generation. Unknown/refused answers do not cause a loop. Readiness reason codes are internal and not exposed as a score.

## 8. Final-result contract

The fourth typed result is `ASSESSMENT_RESULT`: what you told MDQ+, possible explanations, why considered, optional established negatives, next steps, urgent warning signs, limitations, and empty reserved evidence IDs. The provider returns structured explanations with fact IDs and action fields. The server constructs patient facts, negatives, and reasons from verified fact references; it rejects unknown IDs, nonempty evidence IDs, percentage claims, and direct unverified patient assertions. No citations or probability badges are shown. The result is temporary until an explicit Vault save.

## 9. Safety integration

Wave 2 deterministic urgent evaluation runs on every new assessment answer before normal progression. A model proposal may escalate but cannot downgrade that flag. URGENT is terminal and its typed action is retained for temporary recovery. Clinical policy review and physical-device emergency-action testing remain pre-launch obligations; the rule set is deliberately small.

## 10. Resume/expiry behavior

Free and paid authenticated patients can fetch their current temporary assessment. ACTIVE/ABANDONED/READY resume only within 24 hours of last activity. An hourly job marks inactive ACTIVE/READY rows ABANDONED after 24 hours and conditionally deletes temporary rows 72 hours after last activity, including completed, urgent, and cancelled rows. The conditional database DELETE rechecks expiry after lock contention; FK cascade deletes facts/questions. The saved Vault summary, when one exists, is outside this cleanup. A completed or urgent typed result can be recovered within its 72-hour operational window.

## 11. Accounting

Conversation accounting is unchanged. Assessment question/planning/repair turns do not increment text or burst usage. A committed valid result or substantive assessment urgent outcome increments one existing successful text-chat unit. `usage_committed`, terminal state, PostgreSQL claim, and 72-hour assessment receipts prevent double charging/re-generation. Attachment quota availability checks still run; assessment completion is accounted as one text unit, not one unit per internal call. Cancellation, abandonment, provider failure, and invalid final result do not commit completed-use accounting.

## 12. Vault compatibility

No automatic save was added. Flutter's existing Exit & Save sends role/text turns to the existing Vault summary endpoint; `AiAssessmentResult.visibleText` formats the structured sections into readable text rather than JSON. Existing consent, entitlement, idempotency, and source continuation remain. Free users can resume temporary assessment but cannot Save or Continue from Vault.

## 13. Flutter experience

The existing conversation view renders a focused question with the normal free-text composer and server-backed cancel action, a separate structured final-result renderer, and the existing urgent action bubble. It fetches the current session after consent, restores ID/version and Q/A state across controller recreation, carries version through delayed polling, and refreshes authoritative state on a stale-version conflict without appending the conflict as clinical dialogue. READY repair failure exposes a finish retry. No standalone questionnaire or fake progress metric was added.

## 14. Multimodal integration

Existing image/PDF and ownership-checked lab processing are reused. A provider-proposed ATTACHMENT_DERIVED fact is accepted only with an actual current attachment/owned lab reference and a successful structured provider call. A failed media call rolls back the operation and cannot assert that media was reviewed.

## 15. Provider independence

Assessment domain code uses only `ClinicalAIProvider`, `AIGenerationRequest`, and normalized completion. The Gemini adapter maps `assessment` and `assessment_result` purposes to the configured heavy model. No native provider objects, model IDs, or roles enter the assessment schema, Flutter contract, quota logic, or Vault.

## 16. Migration

Apply `backend/migrations/add_ai_assessments.sql` before deploying Wave 3 code. It creates the three tables with patient FK, status/provenance checks, semantic-question uniqueness, and patient/activity/expiry indexes. It is rerunnable with `IF NOT EXISTS` in the repository's SQL migration convention. Existing Wave 1 claim/receipt migrations remain prerequisites. Application startup does not create these new tables as its primary schema mechanism.

## 17. Verification

- Focused Wave 2 + Wave 3 backend: 26 passed.
- Focused Wave 2/3 and PostgreSQL claim/version rerun after selector hardening: **37 passed**. A subsequent focused Wave 2/3 rerun after unknown-answer phrase coverage: **35 passed** (PostgreSQL server already stopped).
- Full backend with a disposable local PostgreSQL instance, before the final selector regression test was added: **356 passed, 2 skipped, 26 subtests passed**. The later focused rerun passed; the entire backend suite was not rerun after that last narrow change. The two skips are environment-dependent tests.
- Final focused Flutter controller/render after READY-retry handling: **30 passed**. Full Flutter before that narrow regression test: **165 passed**; the full suite was not rerun after the last client change.
- `git diff --check`: passed. Changed Dart files were formatted; full `flutter analyze --no-pub` and changed-file `dart analyze` both stalled without diagnostics and were interrupted. Flutter tests compile the changed code, but analyzer status is not claimed clean.
- No live clinical provider or physical-device assessment was exercised. Synthetic evaluation fixture: `backend/tests/fixtures/ai_wave3_scenarios.json` (12 scenarios).

## 18. Environment/deployment requirements

PostgreSQL and the existing AI provider configuration are required. Redis is not required for assessment correctness or AI availability. Deploy the migration first, then backend and Flutter together because the pre-launch client now sends `expected_state_version`. The scheduler must run the hourly retention job. Monitor migration, provider structured-output validity, READY repair failures, cleanup counts, and stale-version conflicts without logging clinical text.

## 19. Physical-device acceptance checklist

- On Free and paid accounts, begin a personal concern, answer one question, terminate/reopen the app, and resume on another device within 24 hours.
- Send conflicting answers from two devices: one succeeds; the other refreshes without a clinical conflict bubble.
- Test detailed initial report, unknown/refusal, contradiction clarification, clear topic switch, cancellation, and mid-assessment emergency escalation.
- Verify long final-result sections, text scaling, screen reader order, and no horizontal overflow on small Android/iOS devices.
- Verify image/PDF failure never claims review, and owned lab data cannot cross accounts.
- Verify failed final repair stays READY and can be retried without usage charge; completed/urgent uses exactly one unit.
- Verify paid Exit & Save produces readable Vault summary and Free remains unable to Save.
- Verify operational rows disappear after 72 hours without affecting an explicitly saved Vault summary.

## 20. Boundaries before the RAG/evidence wave

Nothing in the persistence or typed result contract requires RAG to ship now; `evidence_ids` remains empty. Before enabling evidence claims, define trusted evidence identity, retrieval provenance, citation validity, and source-expiry rules. Before *clinical launch*, separately review question quality, readiness, safety wording/rules, and hallucination-resistant final text with qualified clinicians using real-device and adversarial evaluations. The current syntactic/fact-reference validator does not prove medical correctness. Analyzer completion is also pending on this machine.
