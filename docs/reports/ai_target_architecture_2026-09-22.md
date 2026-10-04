# MDQ+ AI Reform - Target Architecture Design

Date: 2026-09-22  
Status: design only; not approved for implementation  
Repository basis: `docs/reports/ai_architecture_audit_2026-09-20.md` plus the later runtime observations stated in the design brief

## Scope and non-goals

This document defines a target architecture for the patient-facing MDQ+ AI system. It does not change application code, prompts, models, provider configuration, quotas, UI, database schema, Health Vault behavior, retrieval, or web search.

The design preserves the following product boundaries:

- MDQ+ is the only patient-facing AI identity.
- The patient AI reasoning path normally uses one configured primary provider. Gemini remains the development provider; provider competition and automatic provider failover are not part of this design.
- Existing STT and TTS provider choices may remain separate input/output capabilities.
- Conversation, Assessment, and Urgent are the three interaction modes.
- Multimodal data is input to those modes, not another clinical mode.
- Continuation and history are context, not interaction modes.
- No AI-to-doctor handoff is introduced.
- Health Vault is not redesigned. Its existing save/read/continuation contract must remain compatible.

## 1. Architecture principles

1. **Product logic is provider-neutral.** Routing, safety policy, assessment progression, evidence policy, quotas, persistence, and API contracts must not use Gemini/OpenAI role names, payload types, finish reasons, or exception classes.
2. **One active reasoning provider.** A single configured `ClinicalAIProvider` serves patient reasoning in a deployment. A provider switch is an explicit configuration and validation event, not per-request competition or silent failover.
3. **Safety is layered.** Deterministic checks run before and after model reasoning. Model judgment can add safety signals but cannot suppress deterministic ones.
4. **Backend owns clinical workflow state.** Flutter presents state and sends user actions; it does not invent hidden clinical prompts, decide readiness, or reconstruct assessment facts.
5. **Facts and inferences stay distinct.** User-stated facts, model inferences, and retrieved evidence retain provenance. An inference cannot be rewritten as a patient statement.
6. **Evidence is data, not prose decoration.** Retrieval returns validated evidence objects. Citations in patient output must resolve to those objects; the model cannot create source metadata.
7. **Failures are explicit.** Attachment failures, incomplete generations, request timeouts, stale state, and insufficient evidence are represented as typed states. Silent text-only degradation after a failed image is prohibited.
8. **Logical product usage is separate from provider calls.** Metering records patient-visible interactions and assessment lifecycle events independently from internal generation, repair, embedding, retrieval, or reranking calls.
9. **Backward compatibility is additive.** Current Markdown chat and Vault contracts continue during migration. Typed results are introduced through a versioned contract and a dual-capable client.
10. **Privacy is a boundary condition.** Only the minimum required health context crosses each provider boundary. Search queries are de-identified, logs contain operational metadata only, and attachment contents are not logged.
11. **Evaluation gates provider and workflow changes.** A provider adapter is not production-ready merely because it compiles. It must pass structured, safety, grounding, latency, and cost evaluations against a versioned scenario suite.
12. **No big-bang rewrite.** Each phase must preserve a deployable, testable current path and have a rollback switch.

## 2. Domain boundaries

The target remains a modular backend, not a collection of independent microservices. The boundaries below can initially be packages/modules in the existing FastAPI application.

| Boundary | Owns | Must not own |
|---|---|---|
| Interaction API | Authentication, consent gate, request parsing, response version negotiation, transport errors | Clinical routing rules, provider payloads |
| Interaction orchestrator | End-to-end command coordination, request operation, context assembly, mode dispatch | Provider SDK calls, Flutter presentation |
| Safety policy | Deterministic safety checks, safety flag taxonomy, urgent override, post-generation safety validation | General prose generation, provider finish-reason semantics |
| Intent/risk router | Provider-neutral mode recommendation and routing reason codes | Patient-facing response prose, assessment mutation |
| Assessment domain | Session lifecycle, facts, provenance, readiness, question history, transitions | Provider SDK objects, RAG storage implementation |
| Knowledge service | Curated retrieval, trust policy, evidence normalization and merging | Clinical workflow state, patient-facing citation formatting |
| Trusted search gateway | Search trigger authorization, de-identified query, trusted-source filtering | Raw patient conversation, final clinical answer |
| AI provider gateway | Provider adapter, model-purpose mapping, token estimation, structured generation, completion/error normalization | Product quotas, clinical routing policy, persistence decisions |
| Attachment/media boundary | Existing upload validation/storage plus typed processing results | Assuming an attachment was understood when processing failed |
| Usage/accounting | Logical usage events, allowance policy, reservations/commit/refund | Counting provider calls as product usage by default |
| Health Vault | Existing summary save/read/update/idempotency behavior | Active assessment workflow state or automatic saving |
| Observability/evaluation | Safe telemetry, traces, offline scenario execution, release gates | Raw prompts, full responses, attachment contents |

The dependency direction is:

```text
Flutter/API
    -> Interaction orchestrator
        -> Safety + Router + Assessment domain
        -> Knowledge service -> optional trusted search gateway
        -> Provider-neutral AI gateway -> configured provider adapter
        -> Existing media, usage, and Vault boundaries
```

Dependencies flow inward toward domain contracts. Provider adapters, vector stores, search vendors, and database repositories implement ports defined by the domain/application layer.

## 3. Interaction-mode model

### Conversation

Conversation handles ordinary health information, explanations, and discussion where a structured personal symptom assessment is not needed. It should answer directly and ask a follow-up only when the answer would materially improve usefulness or safety.

Conversation is not synonymous with a light model. Mode is a product/clinical decision; model purpose is an internal execution policy.

### Assessment

Assessment is selected when the patient is describing a current or personal health concern and the available information is insufficient for a useful assessment. It creates or continues backend-owned state, asks normally one high-value question at a time, and ends when the controller decides that a result is ready, the patient cancels, the session expires, or safety takes priority.

Assessment is not a fixed questionnaire. Complaint-specific applicability, already-established facts, relevant negatives, and prior questions constrain each next step.

### Urgent

Urgent takes precedence whenever deterministic policy or model-supported reasoning indicates that continuing an ordinary interview is inappropriate. Urgent output is concise, action-oriented, and does not bury escalation guidance under a differential discussion.

Urgent is an interaction result, not a durable diagnosis. An assessment may transition to Urgent at any turn. A later message can be routed again, but the system must not imply that an urgent flag was medically cleared merely because the patient continued chatting.

### Priority and continuity

The effective decision order is:

1. Validate request, consent, entitlement, attachments, and active operation state.
2. Run deterministic safety pre-checks.
3. Resolve whether the message belongs to an active assessment.
4. Route between Conversation and Assessment, with model-added safety signals able to elevate to Urgent.
5. Run a deterministic post-check over the proposed result before release.

When an active, non-terminal assessment ID is valid and the message is a plausible answer or patient action, continuity wins over reclassification. Explicit topic switching may suspend or abandon the old assessment only through a defined controller transition.

## 4. Router contract

### Interface

A conceptual provider-neutral port:

```text
route_interaction(RouterInput) -> RouterDecision
```

This is a domain contract, not a commitment to exact JSON or class names.

### Inputs

`RouterInput` should contain only normalized data:

- current user message or transcript;
- locale/language;
- active assessment summary and version, if any;
- bounded recent interaction context represented with domain roles such as `PATIENT` and `MDQ_PLUS`;
- typed attachment processing results and extracted observations, never provider payloads;
- typed lab record context/reference, when supplied;
- relevant patient context allowed by consent and product policy;
- deterministic pre-safety flags;
- request and interaction identifiers for trace correlation.

### Output

`RouterDecision` conceptually contains:

- proposed mode: Conversation, Assessment, or Urgent;
- confidence expressed in a provider-neutral normalized form;
- stable reason codes from an internal taxonomy;
- normalized presenting concern, if identifiable;
- safety flags with source (`DETERMINISTIC` or `MODEL`);
- continuation disposition: new interaction, continue active assessment, topic switch, cancel intent, or unclear;
- optional clarification need;
- schema version and internal decision metadata.

The router never returns patient-facing prose and never directly updates assessment persistence.

### Responsibility split

Deterministic code owns:

- verified active-assessment lookup and version checks;
- explicit stop/cancel actions;
- attachment status constraints;
- high-confidence safety patterns approved by clinical/product governance;
- precedence rules and low-confidence fallback policy;
- output schema validation.

The configured provider may help with:

- semantic intent classification;
- presenting-concern normalization;
- ambiguity detection;
- contextual safety signals not captured by deterministic extensions.

The router must not contain a clinical rule catalog in application code. Deterministic clinical rules should be versioned policy data with tests and review ownership when such rules are approved.

### Failure and low-confidence behavior

- A deterministic urgent flag always yields Urgent even if provider routing fails.
- A valid active assessment defaults to Assessment if semantic classification is unavailable, unless the patient explicitly cancels or switches topic.
- A new message with clearly personal symptoms but uncertain classification defaults to a minimal Assessment clarification rather than an unsupported final assessment.
- A genuinely ambiguous informational message defaults to Conversation with a concise clarification where needed.
- Malformed router output is rejected, recorded as `STRUCTURED_OUTPUT_INVALID`, and handled by deterministic fallback. Raw malformed content is never passed to the patient.
- Provider timeout does not silently choose a confident clinical route. The request either uses an approved deterministic fallback or returns a retryable typed failure.

### Observability

Safe router telemetry includes request ID, chosen mode, confidence band, reason-code set, safety categories, active-assessment boolean, attachment-status set, latency, provider/model internal identifiers, fallback path, and schema-valid boolean. It excludes message text and normalized concern text.

### Test contract

Router tests must cover:

- direct informational questions;
- clear personal symptom reports;
- follow-up answers within an active assessment;
- explicit cancellation and topic switching;
- deterministic urgent overrides;
- model-only safety signals;
- disagreement between deterministic and model signals;
- low-confidence messages;
- image/PDF/lab contexts in each processing state;
- malformed/empty/timeout provider output;
- invariance to provider-specific role and finish-reason formats;
- no patient-facing prose in the decision object.

## 5. Assessment-state schema proposal

The schema below is conceptual. Exact database types and API field names must be reviewed before migration work.

### Session identity and lifecycle

- assessment/session ID;
- patient owner ID;
- lifecycle status: Active, Ready, Completed, Urgent, Cancelled, Abandoned, or Expired;
- presenting concern and optional complaint category;
- interaction language;
- state schema version;
- optimistic state version;
- created, updated, last-activity, completed, and expiry timestamps;
- originating request ID and latest successful request ID;
- optional source Vault summary reference for context only.

### Clinical case state

- onset;
- duration;
- frequency/pattern;
- progression;
- severity and functional effect;
- associated symptoms;
- relevant negatives;
- medical and risk history relevant to this concern;
- relevant medicines and exposures;
- age context;
- sex/pregnancy-sensitive context only when applicable and permitted;
- red/safety flags;
- facts established;
- questions asked and answers linked to them;
- unresolved or high-value information needs;
- readiness decision, confidence, and reason codes;
- attachment-derived observations and evidence references.

Fields are optional and complaint-dependent. Absence means unknown or not applicable only when explicitly represented; it must not be interpreted automatically as a negative.

### Fact record and provenance

Each material fact should be an addressable record rather than an untraceable field overwrite:

```text
Fact {
  fact_id
  concept
  value
  status: ASSERTED | DENIED | UNCERTAIN | UNKNOWN
  provenance: USER_STATED | MODEL_INFERENCE | RETRIEVED_EVIDENCE | ATTACHMENT_DERIVED
  source_turn_id / attachment_id / evidence_id
  confidence (only where relevant)
  recorded_at
  supersedes_fact_id (optional)
}
```

`RETRIEVED_EVIDENCE` supports clinical context but does not become a fact about the patient. `MODEL_INFERENCE` remains visibly distinct and may guide questioning; it cannot satisfy a required user fact unless the controller explicitly allows an inference for that purpose. Contradictory patient statements create a new fact relationship and an unresolved item rather than silently overwriting history.

### Lifecycle

1. **Creation:** after routing selects Assessment, create state at version 1 with the presenting concern, source message, approved patient context, and any processed attachment observations.
2. **Update:** each accepted patient answer is normalized into proposed facts, validated, merged with provenance, and committed with an incremented version.
3. **Progression:** the controller selects Ask Next Question, Assessment Ready, or Urgent.
4. **Completion:** a validated final assessment result is generated and the session becomes Completed. Completion does not automatically save to Health Vault.
5. **Cancellation:** a patient stop/cancel action transitions to Cancelled and prevents further ordinary updates.
6. **Abandonment:** product policy marks inactive sessions Abandoned after a defined period; they may remain resumable only within an approved window.
7. **Expiry:** operational state and sensitive payloads are deleted or minimized according to a reviewed retention policy.

### Concurrency and versioning

- Every mutation requires `assessment_id` and expected `state_version`.
- The repository performs compare-and-swap or equivalent transactional optimistic locking.
- A stale update returns a typed conflict with the current version; it does not replay model output against newer state.
- One active mutating operation per assessment is allowed. Duplicate idempotency keys return the prior status/result.
- State schema changes are explicitly versioned and migrated; provider-output schema versions are tracked separately.

### Storage recommendation

Use a backend repository abstraction with an operational, server-side store capable of atomic version checks and expiry. A relational table is the safer initial reliability choice because assessment state must survive web-worker restarts and support transactional versioning; Redis may provide leases/cache but should not be the sole source of truth unless loss semantics are explicitly accepted.

This is not Health Vault storage. Active assessment state should be classified as temporary operational health data with an explicit short retention/expiry policy. Long-term retention requires the existing explicit Save to Vault action and existing entitlement/product rules. Exact retention, abandoned-session resume behavior, and whether free users can resume across app restarts remain product/privacy decisions.

Ephemeral data:

- provider-native request/response objects;
- raw model scratch output;
- temporary attachment bytes and signed URLs;
- retrieval query vectors;
- uncommitted proposed state mutations.

Durable only for the operational retention window:

- normalized assessment state and provenance;
- question/answer linkage;
- lifecycle and version metadata;
- operation/idempotency state needed for recovery;
- final typed result until delivery/expiry.

Durable long term only through existing product features:

- explicitly saved Health Vault summary;
- already-durable lab records under existing behavior;
- accounting/audit metadata that contains no raw clinical text.

## 6. Assessment-controller state machine

### Interface

Conceptual application contract:

```text
advance_assessment(AssessmentCommand, CurrentState) -> AssessmentTransition
```

Commands include Start, Submit Answer, Cancel, Resume, and Expire. The transition returns one of Ask Next Question, Assessment Ready, or Urgent, plus a validated proposed state mutation.

### State machine

```text
No Session
  -> Active / Ask Next Question
  -> Active / Ask Next Question (zero or more turns)
  -> Ready / Generate Result
  -> Completed

Active or Ready -> Urgent
Active -> Cancelled
Active -> Abandoned -> Active (only within resume policy)
Active/Abandoned -> Expired
```

`Ready` is an internal checkpoint. The patient receives an `ASSESSMENT_RESULT` only after generation and post-validation succeed. A failed result generation leaves a recoverable Ready state rather than falsely marking completion.

### Transition contract

For every answer, the controller must:

1. verify ownership, lifecycle, expected version, and request idempotency;
2. run deterministic safety checks on the new information;
3. extract proposed facts/inferences through a structured provider contract where needed;
4. validate provenance, allowed concepts, value types, contradictions, and attachment references;
5. merge the accepted mutation transactionally;
6. calculate missing/high-value information candidates;
7. choose exactly one of Ask Next Question, Assessment Ready, or Urgent;
8. generate the relevant typed result;
9. post-validate safety, completeness, evidence references, and output budget;
10. commit the operation result and accounting event.

### Question-selection rules

- Ask one question by default.
- Multiple tightly related items are allowed only when splitting them would be unnatural and the response affordance supports them.
- Rank candidates by expected impact on safety, next-step guidance, and uncertainty reduction.
- Exclude facts already established, questions already answered, and fields irrelevant to this concern.
- Prefer a clear patient-language question over a clinical label.
- Never ask filler solely to prolong an assessment.
- Respect refusal/unknown answers and avoid repeatedly demanding the same information.
- Permit immediate Urgent transition at any turn.

### Deterministic and model responsibilities

Deterministic code owns state transitions, versioning, provenance rules, required schema, duplicate-question checks, terminal-state checks, attachment constraints, approved urgent overrides, and final validation.

The configured provider may propose fact extraction, candidate information needs, ranking, readiness, question wording, and final assessment content. Its proposal is advisory until validated and committed by the controller.

### Malformed output, timeout, and failure

- Structured provider output is parsed against a versioned schema with unknown-field handling defined per version.
- Invalid state mutation is discarded wholesale; partial unvalidated fields are not committed.
- A bounded correction attempt may request schema repair only when the provider returned usable content and the operation budget permits it.
- Repair uses the same logical operation and does not create additional product usage.
- On timeout, the operation becomes Delayed while the backend still owns a valid lease, or Failed when the provider call is conclusively terminated/expired.
- The client receives a typed retryable status and does not append a fabricated MDQ+ answer.
- Repeated provider failure at Ready preserves state for retry; it does not restart questioning.

### Patient stop/cancel

Cancel is a first-class command, not free text that must always be interpreted by a model. The UI may expose a control and the router may also recognize clear textual intent. Cancellation releases the active mutation lease and records a lifecycle transition without saving to Health Vault.

## 7. Provider abstraction

### Provider-neutral contracts

Use one cohesive `ClinicalAIProvider` port with capability-oriented request/response types, rather than provider SDK calls scattered through product services or dozens of microservices. Conceptual capabilities:

- classify/route interaction;
- generate a conversation response;
- propose assessment-state updates;
- choose/word the next question;
- generate a final assessment;
- analyze normalized multimodal input;
- generate a Health Vault summary;
- perform lab interpretation where the existing product still requires model execution;
- estimate/count input;
- inspect completion;
- normalize provider safety and failure state.

Implementations may share an internal generation primitive, but domain callers use purpose-specific typed methods so constraints and schemas remain explicit.

Embeddings should use a separate small `EmbeddingProvider` port because knowledge indexing has a different lifecycle and may use a different technology from the single active reasoning provider. This does not authorize per-task competition among reasoning providers.

STT and TTS remain separate `SpeechToTextProvider` and `TextToSpeechProvider` capabilities under the existing voice boundary.

### Adapter responsibilities

The Gemini adapter owns:

- SDK initialization and credentials;
- provider model names and purpose-to-model mapping;
- conversion from domain conversation roles to Gemini roles;
- image/PDF provider payload construction;
- provider token counting/estimation;
- provider structured-output settings;
- finish/completion inspection;
- safety block and exception mapping;
- provider request timeout/cancellation mechanics;
- removal of provider-native objects before returning.

A future provider adapter must implement the same conformance tests. It may use different native features internally, but cannot change domain or Flutter contracts.

### Domain responsibilities

The domain/application layer owns mode policy, assessment state, readiness and transition acceptance, evidence policy, source validation, quota events, persistence, response envelope, and patient-facing MDQ+ identity.

### Configuration

Configuration should identify:

- active clinical provider;
- model ID by internal purpose/capability, not by UI mode;
- provider timeout profiles;
- input/output budget profiles;
- structured-output schema versions;
- capability flags validated at startup;
- optional embedding backend configuration;
- existing independent voice provider settings.

Provider and model names remain internal operational data. Startup should fail closed for a required missing capability instead of discovering it during a patient request.

### Timeout and error contract

Every provider call receives an absolute deadline derived from the parent operation. Adapters return normalized error categories such as:

- Timeout;
- Rate Limited/Quota Exhausted;
- Authentication/Configuration;
- Safety Blocked;
- Input Too Large;
- Unsupported Media;
- Invalid Structured Output;
- Incomplete Generation;
- Transient Provider Failure;
- Permanent Provider Failure.

The contract also carries retryability, provider request ID where safe, completion metadata, input/output usage, and internal diagnostic detail. Domain code maps these to operation state and safe API errors; it never exposes vendor wording to Flutter.

### Structured-output contract

Purpose-specific output schemas are versioned. The adapter must return either a fully parsed typed object or a normalized failure; it must not return "best effort" provider JSON to the domain. Schema validation, citation ID resolution, and completion status are required before a typed result is considered successful.

### Provider switch definition of done

Switching the primary provider should require only:

- implementing and configuring an adapter;
- passing adapter conformance tests;
- running the versioned MDQ+ evaluation suite;
- reviewing latency, safety, output quality, and cost;
- staged rollout with rollback.

It must not require changes to Flutter, the assessment controller, retrieval/search policy, quota rules, persistence, or Health Vault workflows.

## 8. Retrieval/RAG architecture

### Primary knowledge source

The curated MDQ+ Clinical Library is the primary evidence source. Initial approved content may later include Nigerian Standard Treatment Guidelines, FMOH, NCDC, WHO, selected external guideline bodies, and selected high-quality literature. Inclusion requires content-governance approval; this document does not approve or ingest any source.

### Ingestion boundary

An offline/admin ingestion pipeline should:

1. register a source document and immutable source version;
2. validate ownership/licensing, issuer, publication date, jurisdiction, URL, checksum, and trust tier;
3. extract text with page/section anchors;
4. normalize without losing citation boundaries;
5. create versioned chunks;
6. create embeddings through the provider-neutral embedding port;
7. validate sample retrieval and metadata completeness;
8. publish an index version atomically.

Patient requests never directly ingest arbitrary documents into the curated library. A patient PDF remains patient context, not trusted evidence.

### Document and version lifecycle

- A document identity represents the guidance work; each edition/revision is immutable.
- Exactly defined versions can be Draft, Active, Superseded, Retired, or Withdrawn.
- New index publication references an explicit set of Active versions.
- Retirement removes a source from new retrieval without erasing audit provenance for prior results.
- Urgent withdrawal supports immediate exclusion by evidence ID/version.
- Every response records the retrieval/index version used.

### Chunking

Chunk by clinical section and semantic boundary, preserving headings, tables/lists where possible, jurisdiction, population, and page/section anchors. Chunk size and overlap are corpus/evaluation settings, not provider prompt constants. Each chunk inherits document metadata and has a stable chunk/evidence ID.

### Retrieval and reranking

The knowledge service accepts a de-identified `ClinicalEvidenceQuery` containing concepts, intent, jurisdiction, population qualifiers that are genuinely needed, desired recency, and source-tier constraints.

Recommended flow:

1. metadata filter by active version, jurisdiction, trust tier, and date policy;
2. hybrid semantic/lexical retrieval where supported;
3. optional provider-neutral reranking if evaluation proves value;
4. diversity/deduplication by source and section;
5. evidence sufficiency scoring;
6. return a bounded `EvidenceBundle`.

Vector storage is an implementation choice behind a repository port. PostgreSQL plus a vector extension may reduce operational complexity, but no store should be selected before corpus size, hosting constraints, privacy, and evaluation are known.

### Retrieval failure

No results, stale-only results, conflicting guidance, or below-threshold relevance yields an explicit insufficient-evidence status. The system may then invoke the trusted web-search policy if eligible; otherwise it answers with bounded general guidance/uncertainty or states that reliable evidence is unavailable. It must not fill missing evidence with invented citations.

## 9. Trusted web-search fallback

Web search is optional fallback infrastructure, independently configurable and disabled by default until source policy and evaluation are approved.

### Trigger policy

Search may be considered only when one or more approved conditions are present:

- the curated library has insufficient relevant coverage;
- the question is explicitly time-sensitive;
- current public-health guidance is required;
- a medicine/product alert, recall, outbreak, service detail, or other current fact is required;
- the curated source is known stale for the requested issue.

The orchestrator, not the model alone, authorizes search. Assessment safety does not wait on web search when urgent handling is already indicated.

### Query generation and privacy

Generate a structured, de-identified query from clinical concepts. Remove names, contact information, account identifiers, exact addresses, raw conversation, exact dates not clinically required, and unrelated history. Include geography only at the minimum useful level, such as Nigeria, when needed for guidance applicability.

Query generation is validated before transmission. A policy violation blocks search and records a safe error category without logging the rejected raw query.

### Source policy

Use an allowlist or trust registry for organizations/domains, with tiers and jurisdictional relevance. Candidate results must pass:

- HTTPS and canonical-domain validation;
- allowed organization/domain or explicit reviewed exception;
- publication/update date extraction where relevant;
- title/issuer consistency checks;
- content accessibility and non-redirect abuse checks;
- relevance and clinical-scope checks;
- duplicate and syndicated-content handling.

Untrusted snippets are not evidence. Search result text is treated as untrusted input and cannot override system/domain instructions.

### Normalization and merge

Validated web material is normalized into the same `EvidenceItem` contract as curated retrieval, with source origin `TRUSTED_WEB`, retrieval timestamp, query policy version, and lower/default trust treatment unless policy says otherwise. Curated and web evidence are deduplicated and conflicts are surfaced rather than averaged away.

### Insufficient evidence

If trusted search also fails, the result must explicitly represent insufficient/current evidence. The response can state limitations and provide safe next steps, but cannot cite a search engine, invent a source, or present model memory as current guidance.

## 10. Evidence/source contract

An evidence item should contain:

- stable evidence ID and chunk ID;
- source origin: Curated Library or Trusted Web;
- title;
- issuing organization;
- document identity and version/edition;
- publication/effective date and last-updated date where available;
- section, page, or anchor;
- canonical URL where applicable;
- jurisdiction/population tags;
- trust/source tier;
- indexed date and, for web, retrieved date;
- document/index status;
- content checksum/version;
- bounded excerpt or normalized claim used for generation;
- retrieval relevance metadata kept internal;
- conflict/supersession relationships.

Patient-facing results reference evidence IDs, not arbitrary model-generated URLs. Before release, the response validator must prove that every cited evidence ID exists in the supplied bundle and that rendered title/organization/URL values come from repository metadata. Unreferenced evidence may be omitted from the API response.

The evidence contract distinguishes:

- **patient fact:** something established about this patient;
- **model inference:** a tentative interpretation;
- **evidence claim:** guidance from an identified source.

These types cannot substitute for each other.

## 11. Structured API response design

### Versioned envelope

Introduce an additive v2-style interaction contract while retaining the current v1 `ChatResponse { response, usage_notice, memory_summary }` during migration. The exact route/version mechanism should follow the repository's API versioning convention; a new endpoint is safer than changing the current response in place.

Conceptual envelope:

```text
InteractionResponse {
  api_version
  request_id
  interaction_id
  operation_status
  mode
  result_kind
  result
  assessment_metadata?
  attachment_results[]
  evidence[]
  usage_notice?
  safe_error?
}
```

The result kinds are conceptually Message, Assessment Question, Assessment Result, and Urgent. Names remain reviewable.

### Message result

- Markdown/prose text;
- optional follow-up suggestion metadata;
- evidence references when evidence was actually used.

### Assessment-question result

- one question text;
- assessment/session ID and state version;
- optional answer affordance metadata such as free text, yes/no/unknown, date/duration, or bounded choice;
- progress semantics only if clinically/product-valid; no fake percentage;
- cancel capability.

Affordances are hints, not substitutes for free-text accessibility unless product explicitly decides otherwise.

### Assessment-result result

- concise case summary limited to established patient facts;
- possible explanations framed with uncertainty;
- reasons linked to fact IDs, not invented narrative;
- relevant negatives;
- recommended next steps;
- warning/red-flag advice;
- uncertainty/limitations;
- evidence references;
- assessment/session and result schema versions.

### Urgent result

- immediate action guidance;
- escalation information appropriate to approved policy;
- concise reason category safe for patient display;
- minimal supporting text;
- assessment/session metadata if escalation occurred mid-assessment.

Urgent responses should not expose internal safety flags, provider blocks, or detailed chain-of-thought.

### Error and operation status

Transport success is distinct from clinical result success. A typed safe error includes category, retryability, operation status, and request ID. Provider names/messages remain absent. HTTP status continues to represent auth, validation, conflict, rate limit, and server failure appropriately.

### Backward compatibility

- Keep v1 endpoints and Markdown rendering unchanged initially.
- Add v2 models and endpoint behind a feature flag.
- Make Flutter decode both versions before any user is routed to Assessment.
- Conversation results can be down-converted to v1 Markdown during transition; Assessment Question/Result and Urgent cannot be safely flattened for old clients unless an explicitly reviewed compatibility renderer exists.
- Gate structured modes by client capability/version. Old clients stay on existing conversation behavior until minimum-version policy changes.
- Vault saving continues to receive conversation turns under its current contract; typed result serialization into save turns requires a compatibility formatter, not raw JSON.

## 12. Flutter state/rendering implications

Flutter should replace the assumption that every AI response is one Markdown string with a sealed/domain model such as:

- message;
- assessment question;
- assessment result;
- urgent guidance;
- operation status/error.

Required state implications:

- retain request ID, interaction ID, operation status, and retry metadata;
- retain active assessment ID and expected state version;
- represent attachment processing status explicitly;
- disable ordinary Send while an operation is Sending, Processing, or Delayed;
- expose cancel only when the backend operation/session supports it;
- render stale-state conflicts by refreshing state rather than appending an error as clinical dialogue;
- keep current Markdown bubble for Message results;
- add dedicated, accessible renderers for question, result, urgent, and evidence references;
- serialize typed results into human-readable existing Vault turns when Save is invoked;
- stop building provider/system-like lab prompts in Flutter.

The controller should send domain roles (`patient`, `mdq_plus`) or interaction IDs, not Gemini's `model` role. Provider-specific history formatting moves entirely to the configured adapter.

The current conversation screen and navigation can remain; this design does not require a Health Vault redesign or a new doctor workflow.

## 13. Multimodal integration

Existing image upload, PDF validation, lab scanner, and voice transcription are reused. The orchestrator receives normalized attachment inputs and routes them through an attachment-processing boundary before clinical routing.

### Attachment processing result

Every attachment returns one of:

- **Processed:** validated, analyzed/extracted as required, with typed observations and capability metadata;
- **Failed:** validation/fetch/provider processing failed, with safe category and retryability;
- **Unsupported:** valid transport but unsupported format/capability for this interaction/provider.

The result also carries attachment ID, media kind, temporary/durable reference policy, and processing version. Provider-native payloads and signed URLs do not enter assessment state.

### Domain decision

- If an attachment is essential to the patient's request and status is Failed/Unsupported, the system returns an explicit attachment result and asks for retry/alternative. It must not claim to have considered it.
- If the text independently supports a useful response, the domain may continue only while explicitly telling the response generator and API that the attachment was not considered.
- Quota accounting follows approved logical-use policy and must distinguish failed attachment processing from successful analysis.
- Temporary image/PDF cleanup remains guaranteed on all terminal paths.

### Lab context

Flutter sends a typed lab record/result reference plus the patient's question. The backend loads/validates ownership and turns the lab data into provider-neutral clinical context. Provider prompt representation belongs in the adapter/domain generation layer. The existing lab analysis endpoint and durable lab record remain separate capabilities; only follow-up transformation moves out of Flutter in a later phase.

### Voice transcript

STT remains input preparation. The patient can review/edit the transcript before send. Once sent, the transcript follows the same router and assessment path as typed text, with metadata indicating transcription provenance where useful.

## 14. Request lifecycle/concurrency design

### States

Use the shared lifecycle:

```text
IDLE -> SENDING -> PROCESSING -> SUCCEEDED
                         |-----> DELAYED -> SUCCEEDED | FAILED | CANCELLED
                         |-----> FAILED
                         |-----> CANCELLED
```

`SENDING` is primarily client transport state. `PROCESSING`, `DELAYED`, and terminal states are backend operation states. A client timeout does not prove backend failure.

### Operation and lease

Each mutation has:

- client-generated idempotency/request key;
- server operation ID;
- patient/assessment owner;
- canonical payload hash;
- state and timestamps;
- lease owner/token and lease expiry;
- provider deadline;
- result/error reference;
- assessment version read and version committed.

The backend acquires a short renewable lease before provider work. Lease expiry allows recovery of abandoned work, but must not permit two workers to commit the same assessment version. Final commit is protected by idempotency and optimistic state versioning even if leases overlap during failure recovery.

### Client behavior

- Disable normal Send during Sending, Processing, or Delayed.
- Show a neutral progress/delay state without claiming failure while backend status is unknown.
- On client timeout, query operation status using the same request/operation ID rather than sending a new clinical message.
- Retry uses the same idempotency key for the same canonical payload; edited content creates a new key.
- App restart may recover a non-terminal operation from a status endpoint if product privacy/session policy permits.

### Backend cleanup

- Provider success commits result, assessment mutation, operation status, and accounting atomically where practical.
- Provider error marks Failed, records normalized category, and releases/expires lease in `finally` semantics.
- Provider timeout marks Delayed only while continued work is real and recoverable; after deadline it marks Failed.
- Process death leaves a lease that expires; a recovery worker or later status request can safely resume/fail the operation according to policy.
- No terminal operation may leave an active per-user guard indefinitely.

### Duplicates and retries

- Same key plus same payload returns current status or prior result.
- Same key plus different payload returns conflict.
- A second independent Send while an assessment mutation is active returns an operation-in-progress conflict with the active operation ID.
- Retryable provider failure can create a linked attempt under the same logical operation; product usage remains one logical event.
- Result replay does not invoke the provider or consume quota again.

### Cancellation

Cancellation is best effort. The backend marks cancellation requested, invokes provider cancellation if supported, prevents uncommitted output from becoming a patient result, and releases resources. If a result committed first, status remains Succeeded. Cancelling a request is distinct from cancelling/abandoning the assessment session; the API must name which action occurred.

## 15. Output/token-budget strategy

Use purpose-specific budget profiles, measured and adjusted through evaluation. Do not solve the current 500-token failure by globally increasing limits.

| Output purpose | Policy |
|---|---|
| Conversation | Bounded concise answer; reserve room for safety and evidence references; allow a short follow-up only when useful |
| Assessment question | Very small budget; one question plus minimal context; schema overhead is reserved first |
| Assessment result | Larger bounded budget with mandatory sections and evidence IDs; prioritize completeness over stylistic detail |
| Urgent | Small deterministic/action-first budget; emergency guidance must fit without continuation |
| Vault summary | Existing bounded continuity summary behavior, moved behind the configured provider adapter; preserve chunk/final strategy until separately changed |

### Input budgeting

The orchestrator allocates an input budget across system policy, active assessment facts, recent turns, saved summary context, attachments, and evidence. Structured state should replace repeated raw history where possible. Trimming is deterministic and records what context categories were omitted; safety-critical state is not trimmed before conversational detail.

### Completion guarantees

- Structured results reserve output tokens for all required fields.
- Adapters inspect native finish state and return Incomplete Generation when completion is not reliable.
- A schema-valid but semantically missing required section is incomplete.
- The API never releases truncated JSON or an assessment result missing its safety/next-step fields.
- Urgent guidance should have a deterministic minimum safe fallback that does not depend on repair.

### Repair/continuation

- Permit at most a bounded, purpose-specific repair attempt under the same operation budget.
- Repair should request a complete replacement typed result, not concatenate arbitrary continuations.
- For long evidence-grounded results, regenerate from compact structured state/evidence rather than feed an already-truncated response back as truth.
- If repair fails, preserve assessment state at Ready and return a typed retryable failure. Do not mark Completed or consume successful logical usage.
- Conversation may return a shorter validated fallback only if it remains responsive to the question and safe; otherwise return a retryable failure.

## 16. Voice-input contract

STT remains an independent input capability. The contract must align five layers:

1. **Recorder:** explicitly configured output container and codec, sample-rate/channel constraints, and finalized file before upload.
2. **Client metadata:** filename extension and MIME derived from the actual encoded file, not a hard-coded assumption.
3. **Transport:** multipart part preserves filename, MIME, byte length, language, and request ID.
4. **Backend validation:** validates signature/container and supported codec consistently, returns a precise safe unsupported/invalid category, and does not trust extension alone.
5. **STT adapter:** maps the validated media to the provider request and normalizes timeout/format/provider errors.

The target supported-format matrix must be a shared contract and test fixture. At minimum it must settle whether the product standard is M4A with AAC and/or WAV with PCM, because accepting a container without its actual codec is insufficient.

Later implementation areas, not changed here:

- `frontend/lib/src/features/chat/data/voice_input_service.dart` for recorder output and multipart metadata;
- the recorder/controller integration in the chat presentation layer for finalization and error state;
- `backend/app/api/v1/voice.py` for upload contract and safe error mapping;
- `backend/app/services/voice_transcription.py` for signature/container/codec validation and provider adapter input;
- `frontend/lib/src/features/chat/data/voice_input_capability.dart` only if the supported language/format matrix changes;
- corresponding `voice_input_test.dart` and `test_voice_transcription.py` fixtures with real encoded samples.

The observed physical-device error, "This audio file could not be processed. Use an M4A or WAV recording.", should be diagnosed against this contract in a separate implementation task.

## 17. Save-to-Vault compatibility

Health Vault remains an explicit existing feature. This architecture does not redesign or repair it.

Compatibility requirements:

- preserve `POST /api/v1/vault/ai-summary/save` request/response and idempotency behavior during the migration;
- preserve paid entitlement, consent, continuation ownership/version checks, and current history rendering;
- continue sending human-readable turns, not provider-native objects or raw structured JSON;
- introduce a domain formatter that can represent Message, Assessment Question, Assessment Result, and Urgent turns as summary input without changing the public save payload initially;
- route future summary generation through `ClinicalAIProvider.generate_summary` using the configured primary provider;
- keep persistence and provider-generation errors distinguishable internally but safely mapped to the existing client contract;
- do not automatically save completed assessments.

The latest runtime evidence supplied for this design says the observed Save failure occurs during summary generation because the configured Gemini heavy-model quota is exhausted before persistence. That evidence supersedes schema drift as the explanation for that specific observed attempt, but it does not prove deployed schema correctness. Both concerns remain separate operational checks. No provider billing/quota or schema fix belongs to this design task.

## 18. Quota/accounting hooks

Accounting must record logical product events separately from internal resource usage.

### Logical events

Conceptual events include:

- interaction started/succeeded/failed/cancelled;
- conversation response delivered;
- assessment started;
- assessment question delivered;
- assessment completed;
- assessment abandoned/expired;
- urgent result delivered;
- attachment analysis succeeded/failed;
- Vault summary saved;
- STT transcription succeeded;
- TTS synthesis succeeded.

Each event carries a stable logical interaction/assessment ID, user/plan dimensions, timestamp, and policy version without raw clinical content.

### Internal cost events

Separately record provider operation purpose, provider/model internal IDs, token/input/output metrics, media units, embedding/retrieval/reranking operations, repair attempts, latency, and normalized failure. These support cost and performance analysis but do not directly decrement patient allowance.

### Reservation and commit

- Policy checks/reserves the logical unit before expensive work when necessary.
- Successful patient-visible outcome commits usage according to the active product policy.
- Failed/cancelled operations release reservations unless policy explicitly defines otherwise.
- Duplicate/result replay never charges twice.
- Multiple provider calls, repairs, retrievals, or question turns can be grouped under one assessment ID, allowing a future "one completed assessment use" rule without schema reinvention.

Current quotas and pricing remain unchanged until a product decision and migration explicitly activate new accounting policy.

## 19. Privacy/observability

### Data minimization

- Build purpose-specific context; do not send the complete profile by default.
- Send only bounded relevant history/state to the configured provider.
- De-identify web-search concepts before transmission.
- Keep patient PDFs/images as untrusted patient context, not library evidence.
- Retain active assessment data only for an approved operational period.
- Do not persist provider-native prompts/responses for debugging by default.

### Safe logs and metrics

Allowed operational metadata:

- internal request, operation, interaction, and assessment IDs;
- interaction mode/result kind;
- state and schema versions;
- provider/model IDs in restricted internal telemetry;
- purpose, latency, token/media usage, and call count;
- completion and normalized error category;
- safety category/reason codes without raw triggering text;
- attachment kind and processing status, not content/URL;
- retrieval index version and evidence IDs;
- search used boolean, source organizations/domains, and policy result;
- quota/accounting event and policy version.

Do not log:

- raw medical prompts/messages;
- full model responses;
- assessment facts or case summaries in ordinary logs;
- raw/de-identified search query text unless separately approved and protected;
- attachment bytes, extracted content, signed URLs, or voice audio;
- provider credentials or full provider error payloads that may echo content.

### Tracing and access

Use correlation IDs across API, operation, retrieval, and provider spans. Apply field allowlists/redaction before telemetry export. Restrict provider/model and cost dashboards to internal roles. Define retention, access review, incident handling, and deletion behavior for traces before structured assessment rollout.

## 20. Evaluation framework

Build a versioned offline evaluation harness before activating new routing/assessment behavior or switching providers.

### Scenario format

Each fixture should contain:

- de-identified synthetic patient turns and optional attachments/lab context;
- locale/language and approved profile context;
- expected mode or acceptable modes;
- expected/forbidden safety flags;
- required facts and provenance behavior;
- high-value next-question characteristics;
- readiness constraints;
- expected evidence IDs/source characteristics where retrieval is tested;
- forbidden conclusions/citations;
- latency and budget envelope;
- fixture version and reviewer provenance.

No real patient conversation should enter the suite without an approved de-identification and governance process.

### Metrics

- routing accuracy and calibration;
- urgent/red-flag sensitivity plus false escalation rate;
- question usefulness/information gain;
- repeated, irrelevant, or unnecessary question rate;
- information sufficiency and appropriate stopping;
- premature conclusion rate;
- fact/provenance accuracy;
- evidence grounding and claim support;
- citation existence, metadata correctness, and source trust;
- uncertainty quality;
- structured-output validity and completion rate;
- attachment failure honesty;
- latency percentiles;
- token/media/call cost by logical interaction;
- repair and failure rates.

### Evaluation methods

Use deterministic validators for schemas, provenance, duplicate questions, evidence-ID resolution, budgets, and safety invariants. Use clinically reviewed rubrics for question usefulness, sufficiency, uncertainty, and next-step quality. Model-based judging may assist but cannot be the sole safety gate; judge configuration and bias must be versioned.

### Release gates

- Provider adapter conformance passes.
- No regression on deterministic safety invariants.
- Structured validity and citation resolution meet agreed thresholds.
- Clinical/product reviewers approve representative failures.
- Shadow and canary telemetry meet latency/failure targets.
- Rollback path is tested.

The same suite runs against Gemini today and any future adapter candidate. This document does not compare providers.

## 21. Data/schema implications

No schema is created by this design. Likely future entities/contracts are classified below.

| Area | Classification | Likely impact |
|---|---|---|
| Current chat endpoints and `ChatResponse` | REUSE then DEPRECATE selectively | Remain for old clients; conversation compatibility path |
| Existing auth, consent, entitlement, media validation | REUSE | Called by new orchestrator |
| Existing request guard/idempotency concepts | REFACTOR | General operation state, leases, replay, assessment ownership |
| `ai_service.py` Gemini execution | REFACTOR | Split provider-neutral port/policy from Gemini adapter |
| Current prompt/model policy | REFACTOR later | Purpose-specific generation behind domain contracts; no prompt change in this task |
| Provider-specific frontend history roles | DEPRECATE | Replace with domain roles/interaction references |
| Interaction operation entity | NEW | Lifecycle, payload hash, lease, result/error, idempotency |
| Assessment session entity | NEW | Owner, lifecycle, version, concern, readiness, timestamps, expiry |
| Assessment fact/provenance entity or structured field set | NEW | Facts, source references, supersession/contradiction |
| Assessment question/answer linkage | NEW | Avoid repeats and preserve provenance |
| Typed v2 interaction schemas | NEW | Message/question/result/urgent and attachment status |
| Flutter sealed response/state models | NEW | Typed decode/render/recovery |
| Clinical document/source registry | NEW | Immutable versions, trust, status, checksums |
| Evidence chunk/index metadata | NEW | Stable IDs, anchors, embedding/index version |
| Retrieval/search policy contracts | NEW | Sufficiency, trust, normalization, de-identification |
| Logical usage ledger/events | NEW or REFACTOR | Decouple product accounting from provider calls |
| Existing quota counters | REUSE initially | Current rules remain active during migration |
| Existing Vault summary/idempotency entities | REUSE | No redesign; summary generation adapter refactor only |
| Existing lab records | REUSE | Typed reference/context replaces Flutter hidden prompt |
| Frontend `_buildSystemPrompt` lab transformation | DEPRECATE | Backend-owned typed lab context |
| Hidden memory tag protocol | DEPRECATE eventually | Backend-owned structured context/state supersedes provider markup |
| Provider-specific completion/error mapping in domain code | DEPRECATE | Adapter-normalized contracts |

Likely migration requirements include operation tables, assessment state/facts/questions, evidence registry/document/chunk/index metadata, and optional usage ledger. Exact normalization versus JSON columns, retention indexes, encryption, row-level access, and deletion jobs require a separate schema design/review.

## 22. Migration/backward-compatibility strategy

1. Put provider-neutral interfaces around current behavior without changing outputs.
2. Add operation/idempotency state while preserving synchronous v1 behavior.
3. Add the typed response contract and Flutter dual decoding behind capability flags.
4. Run router in shadow mode and compare decisions without changing patient responses.
5. Enable typed Conversation for capable clients, retaining Markdown content.
6. Introduce assessment persistence/controller behind a narrow feature flag and cohort.
7. Enable Urgent typed handling only after deterministic policy and fallback review.
8. Add curated retrieval first in shadow/trace mode, then patient-visible evidence.
9. Add trusted search only after curated sufficiency and source-policy behavior are measured.
10. Migrate lab follow-up, multimodal generation, summary generation, and old memory/history coupling incrementally.

Compatibility controls should include server feature flags, client capability/version negotiation, schema versions, provider adapter rollback, route-level fallbacks, and data migration rollback/forward strategy. Old clients must never receive an unsupported result kind.

## 23. Implementation phases

### Phase 0 - Contracts, baselines, and evaluation skeleton

- **Prerequisite:** architecture/product review of this document.
- **Scope:** define domain types, error taxonomy, safe telemetry fields, scenario format, current-behavior baseline fixtures, and feature-flag strategy. No production behavior change.
- **Likely components:** new internal contract/evaluation packages; tests around current `ai_service.py`, chat routes, controller fixtures, and telemetry redaction.
- **Backward compatibility:** complete; current endpoints unchanged.
- **Tests:** schema/type tests, log-redaction tests, baseline conversation/image/PDF/Save fixtures.
- **Rollout risk:** low; risk is encoding current defects as desired behavior, so baselines must distinguish observation from requirement.
- **Exit criteria:** approved contracts and error taxonomy; repeatable baseline suite; raw content absent from telemetry.

### Phase 1 - Provider-neutral gateway under current behavior

- **Prerequisite:** Phase 0 contracts and baseline.
- **Scope:** introduce `ClinicalAIProvider`, Gemini adapter, purpose/model config, normalized completion/error handling; route existing chat and summary generation through it without prompt/model changes.
- **Likely components:** `backend/app/services/ai_service.py`, `ai_summary_service.py`, lab execution, new provider package/config wiring, backend tests.
- **Backward compatibility:** v1 API and Flutter unchanged; Gemini remains active provider.
- **Tests:** adapter conformance, golden behavior equivalence, multimodal payload, completion mapping, quota behavior, summary failure mapping.
- **Rollout risk:** medium because every existing AI path is touched; use per-capability flags and immediate rollback.
- **Exit criteria:** no provider SDK types in domain callers; existing suite and evaluation baseline pass; configured Gemini behavior is equivalent.

### Phase 2 - Recoverable request lifecycle and attachment truthfulness

- **Prerequisite:** normalized provider timeout/error contract.
- **Scope:** operation IDs/status, payload hashing, lease cleanup, duplicate/retry semantics, delayed state, explicit attachment Processed/Failed/Unsupported results; preserve current response where possible.
- **Likely components:** `ai_request_guard.py`, chat routes, media/PDF boundary, new operation repository/schema, `AiChatController`, API client/error mapper.
- **Backward compatibility:** v1 can still wait synchronously; operation metadata may be additive headers/fields. Old clients retain safe failure behavior.
- **Tests:** client timeout with backend completion, lease expiry, process/provider failure cleanup, duplicate key replay, hash conflict, image-fetch failure, send disabled while active.
- **Rollout risk:** medium-high due to concurrency and new persistence.
- **Exit criteria:** no stuck "already processing" after terminal failure; duplicate requests do not duplicate generation/accounting; failed images are never treated as processed.

### Phase 3 - Typed API envelope and Flutter dual rendering

- **Prerequisite:** operation lifecycle and approved result schemas.
- **Scope:** additive v2 interaction endpoint/envelope; Flutter sealed models; Message renderer using current Markdown; placeholders/feature-gated renderers for question/result/urgent; domain roles replace provider roles at the API boundary.
- **Likely components:** FastAPI schemas/routes, `ai_chat_controller.dart`, chat screen message models/widgets, repository/API client, tests.
- **Backward compatibility:** v1 unchanged; capable Flutter client negotiates v2; server sends only Message until later flags activate.
- **Tests:** dual decoding, unknown result version, old-client behavior, Vault turn formatting, accessibility/golden tests, provider-name redaction.
- **Rollout risk:** medium, primarily client/server version skew.
- **Exit criteria:** capable clients reliably render typed Message and operation state; old clients remain functional; unsupported kinds cannot reach old clients.

### Phase 4 - Safety layer and router in shadow, then controlled mode routing

- **Prerequisite:** typed contract, evaluation fixtures, clinical/product ownership for safety reason codes.
- **Scope:** deterministic safety extension points, router contract/adapter method, low-confidence policy, shadow decisions, then enable Conversation/Urgent routing for a controlled cohort.
- **Likely components:** new safety/router modules, orchestrator, provider structured schemas, observability/evaluation harness.
- **Backward compatibility:** initial shadow has no behavior change; fallback returns current Conversation behavior.
- **Tests:** router contract suite, urgent precedence, low confidence, malformed output, multilingual and multimodal context, shadow divergence dashboards.
- **Rollout risk:** high because routing affects safety and user experience.
- **Exit criteria:** agreed routing/safety metrics, reviewed false positives/negatives, deterministic urgent fallback proven, rollback flag tested.

### Phase 5 - Backend assessment state and controller

- **Prerequisite:** active router, operation/version semantics, approved retention and state schema.
- **Scope:** assessment repository, lifecycle, facts/provenance, controller, question selection, readiness, cancellation/expiry, typed result generation behind a feature flag.
- **Likely components:** new assessment domain/repository/models/migrations, orchestrator, provider schemas, expiry jobs, accounting hooks.
- **Backward compatibility:** only capable clients/cohorts enter Assessment; others remain Conversation.
- **Tests:** state transitions, optimistic conflicts, provenance, contradiction, no repeated questions, urgent early exit, cancel/expiry, malformed provider output, result retry from Ready.
- **Rollout risk:** very high; this is the central clinical workflow.
- **Exit criteria:** evaluation thresholds met; no inference promoted to user fact; lifecycle/retention verified; complete question/result path works without Vault.

### Phase 6 - Full Flutter assessment experience

- **Prerequisite:** stable controller/API contracts and usability designs approved separately.
- **Scope:** production question/result/urgent renderers, answer affordances, session recovery/cancel, stale-state handling, evidence placeholders, analytics events.
- **Likely components:** chat presentation/controller/models/router, accessibility/localization tests.
- **Backward compatibility:** feature/capability flags; current Markdown Conversation remains.
- **Tests:** widget/golden/integration tests, process restart recovery, slow operation, cancel, stale version, long/localized text, Save formatting.
- **Rollout risk:** medium-high; presentation mistakes can obscure urgent guidance or create duplicate sends.
- **Exit criteria:** end-to-end device tests pass across supported layouts/languages; Send concurrency is enforced; urgent content remains prominent and accessible.

### Phase 7 - Curated clinical library and grounded generation

- **Prerequisite:** source governance, evidence contract, approved corpus/licensing, embedding/store decision.
- **Scope:** registry, versioned ingestion, chunking/indexing, retrieval/sufficiency, evidence validator, shadow retrieval then cited outputs.
- **Likely components:** ingestion/admin tooling, knowledge repositories, embedding adapter, orchestrator/provider inputs, API evidence objects, Flutter evidence renderer.
- **Backward compatibility:** retrieval can be disabled; no citation shown unless validated.
- **Tests:** ingestion/version/retirement, retrieval relevance, trust filters, prompt-injection resistance, citation resolution, conflicting/stale sources.
- **Rollout risk:** high due to clinical grounding and content lifecycle.
- **Exit criteria:** approved corpus indexed reproducibly; citation correctness threshold met; withdrawal works; no manufactured citations.

### Phase 8 - Trusted web-search fallback

- **Prerequisite:** curated retrieval sufficiency measurement, source registry/policy, privacy review.
- **Scope:** trigger policy, de-identified query generator, search adapter, trusted-domain validation, normalization/merge, insufficient-evidence behavior.
- **Likely components:** trusted-search gateway, policy/config, knowledge service, observability/evaluation.
- **Backward compatibility:** disabled by default and independently switchable.
- **Tests:** PII stripping, allowlist/redirect validation, stale/current guidance, malicious snippets, no-results/conflicts, evidence provenance.
- **Rollout risk:** very high because data leaves another boundary and current web content is untrusted.
- **Exit criteria:** privacy and source-policy review passes; search activates only on approved triggers; all displayed sources resolve to validated evidence.

### Phase 9 - Multimodal, lab, voice, and summary consolidation

- **Prerequisite:** stable orchestrator/provider/typed contracts; separate fixes approved for observed voice and Save failures.
- **Scope:** typed lab references replace Flutter hidden prompt; all image/PDF analysis uses attachment-state contract; voice format contract implementation; Vault summary uses configured provider adapter; remove obsolete provider-specific memory/history paths when safe.
- **Likely components:** lab/chat/voice routes and services, Flutter lab/voice controllers, summary service, media cleanup, tests.
- **Backward compatibility:** preserve lab records, voice UX, Vault endpoint, and old clients until deprecation criteria are met.
- **Tests:** real media fixtures/device tests, typed lab ownership, failed attachment honesty, temporary cleanup, summary idempotency, real migrated DB Save-to-Vault integration.
- **Rollout risk:** medium-high across several existing capabilities; split into independently deployable subphases.
- **Exit criteria:** no hidden clinical prompt in Flutter; supported device recordings transcribe; summary path is adapter-backed; v1/provider-specific paths have measured deprecation readiness.

### Phase 10 - Accounting policy activation and legacy retirement

- **Prerequisite:** product decision on logical assessment usage; stable telemetry and client adoption.
- **Scope:** activate logical accounting rules, reconcile/reserve/commit events, deprecate old endpoint/history role/memory tag paths, complete provider-switch rehearsal.
- **Likely components:** usage service/schema, feature flags, old chat service/API, dashboards, migration/cleanup jobs.
- **Backward compatibility:** announce minimum client version and preserve read access to existing Vault data.
- **Tests:** no double charge, multi-call assessment accounting, replay/refund, downgrade paths, provider switch evaluation, rollback.
- **Rollout risk:** high for entitlement/billing semantics; requires staged reconciliation.
- **Exit criteria:** approved quota policy is auditable; legacy traffic is negligible/blocked by version policy; provider switch can be executed without product-layer edits.

## 24. Risks/trade-offs

| Risk/trade-off | Architectural response |
|---|---|
| Deterministic safety can miss semantics; model safety can be inconsistent | Layer both, give deterministic flags precedence, evaluate disagreement and fallbacks |
| Backend assessment persistence improves continuity but stores sensitive health data | Separate operational state from Vault, minimize fields, define short expiry and deletion before rollout |
| Structured workflows can feel interrogative | One high-value question, readiness stopping rule, cancel path, direct Conversation mode |
| One provider simplifies behavior but creates provider availability dependency | Explicit normalized failures and tested adapter replacement; no unapproved silent failover |
| Provider-neutral interfaces can become lowest-common-denominator abstractions | Use purpose-specific typed capabilities and allow adapter internals, while keeping domain invariants stable |
| RAG may retrieve irrelevant or outdated guidance | Versioned curated corpus, trust/date filters, sufficiency threshold, retirement/withdrawal, evaluations |
| Web search adds privacy and untrusted-content risk | Strict trigger, de-identification, source registry, validation, disabled-by-default rollout |
| Typed API creates client/version complexity | Additive endpoint, capability negotiation, dual client, never send unsupported kinds |
| Async/recoverable operations add state and schema complexity | Introduce before assessment, keep one operation model, require idempotency and cleanup tests |
| Model-generated state updates may corrupt facts | Proposed mutations are schema/provenance validated and transactionally committed; discard invalid output |
| Token repair can multiply cost and latency | Purpose budgets, bounded repair, logical accounting separate from provider calls |
| Evidence citations can create false confidence | Link claims only to validated IDs, show uncertainty, test support and source trust |
| Existing Save/voice runtime failures can be confused with reform regressions | Establish separate baseline diagnostics and integration tests before migrating those paths |

## 25. Open product decisions

The following decisions are required before their dependent phases:

1. Active/abandoned assessment retention period, resume window, deletion semantics, and whether free users can resume after app restart.
2. Clinical/product owner and approval process for deterministic safety rule data, emergency wording, pregnancy/pediatric/self-harm extensions, and reason-code taxonomy.
3. Whether an ambiguous personal-symptom message should default to a single assessment clarification or require an explicit "start assessment" confirmation.
4. Exact required sections and patient-language presentation of the final assessment result.
5. Whether answer affordances are offered and which questions must always permit free text/unknown/refusal.
6. Approved curated source list, licensing, trust tiers, jurisdiction policy, update cadence, and withdrawal authority.
7. Trusted web domain policy, permitted trigger categories, and whether search is available in all plans/regions.
8. Evidence/citation display depth in Flutter and whether links open externally with an interstitial.
9. Logical quota semantics: per successful conversation turn, per assessment start, per completed assessment, or another rule; treatment of abandoned/urgent assessments.
10. Minimum supported client/version for typed Assessment and Urgent results.
11. Whether typed operational assessment state may be used to resume across devices before explicit Vault save.
12. Supported recorder container/codec matrix and device/OS coverage for voice input.
13. Provider timeout targets and user-facing delayed/cancel behavior by operation type.
14. Whether completion of an assessment should merely offer the existing Save action or leave Save only on exit; Health Vault itself remains unchanged.
15. Legal/consent wording for provider processing, retrieval, web search, and temporary assessment-state retention while keeping provider names out of ordinary UX.

## LOCKED FROM CURRENT PRODUCT

- MDQ+ is the sole patient-facing AI identity.
- One configured primary reasoning provider is active at runtime; Gemini is the development provider today.
- Existing independent STT/TTS behavior may remain.
- The three modes are Conversation, Assessment, and Urgent.
- Multimodal is input; continuation/history is context.
- No AI-to-doctor handoff is introduced.
- Current image, PDF, lab, voice, quota, consent, entitlement, and Health Vault capabilities are preserved through compatible boundaries.
- Save to Vault remains explicit and is not redesigned or automatically triggered.
- Current quotas remain unchanged until a later product decision and implementation.
- Provider/model/prompt/retrieval/search internals are not ordinary patient-facing information.

## ARCHITECTURE RECOMMENDATIONS

- Place an interaction orchestrator over safety, router, assessment, knowledge, provider, operation, and accounting ports within the existing backend.
- Introduce a cohesive provider-neutral `ClinicalAIProvider` and keep one configured reasoning adapter.
- Store assessment state backend-side with provenance, optimistic versioning, operation recovery, and explicit expiry, separate from Health Vault.
- Add a typed, additive API contract and dual-capable Flutter client before enabling Assessment.
- Build curated, versioned evidence retrieval before trusted web fallback.
- Treat every attachment and completion outcome explicitly; never silently imply that failed media was considered.
- Meter logical product outcomes separately from internal provider calls.
- Gate routing, safety, grounding, and provider changes with a versioned evaluation harness.

## PRODUCT DECISIONS STILL REQUIRED

- Assessment retention/resume policy and final-result presentation.
- Deterministic clinical safety governance and exact escalation policy.
- Approved evidence corpus, trust tiers, licensing, and trusted web policy.
- Logical assessment quota semantics.
- Client-version rollout policy, evidence UX, and voice codec matrix.
- Search/provider processing consent and temporary-state privacy language.

## IMPLEMENTATION ORDER

1. Contracts, safe observability, and evaluation baseline.
2. Provider-neutral gateway preserving current Gemini behavior.
3. Recoverable request lifecycle and explicit attachment state.
4. Typed API envelope and Flutter dual rendering.
5. Safety/router shadow mode, then controlled routing.
6. Backend assessment state/controller, then full Flutter assessment UI.
7. Curated clinical library and grounded evidence output.
8. Trusted web-search fallback.
9. Multimodal/lab/voice/Vault-summary consolidation.
10. New logical accounting policy activation and legacy retirement.

## DO NOT IMPLEMENT YET

Do not change application source, prompts, models, environment variables, quotas, UI, database schema, provider billing, Health Vault, RAG, web search, or voice/media behavior from this document. Review and approve the domain contracts, safety governance, privacy/retention choices, evidence policy, API versioning, and implementation sequence before coding.
