# MDQ+ AI Reform Wave 4: Curated Knowledge and Grounding

## Scope and source registry

Wave 4 adds the explicit migration `backend/migrations/add_clinical_knowledge.sql` for approved curated sources, immutable document versions, evidence chunks and index-build metadata. Source identity, licensing approval, jurisdiction and trust tier are distinct from patient documents and future web evidence. The CLI is internal-only; there is no public mutation route. Production library content is currently **empty**. Clinical and licensing review remains the activation gate; see `mdq_clinical_source_intake_2026-09-25.md`.

## Lifecycle and ingestion

The operator registers an approved source, ingests a PDF/UTF-8 text/Markdown edition as DRAFT, reviews it, then explicitly activates it. Activation locks the source and version, verifies a complete index and chunk count, and supersedes the prior ACTIVE edition in one transaction. A partial parse, embedding failure, or uncommitted DB transaction never becomes ACTIVE. Identical checksum+edition is idempotent; changed bytes require a new edition. Published document metadata and chunks cannot be edited. RETIRED/WITHDRAWN/SUPERSEDED editions remain for audit but are excluded from new retrieval. Reindexing uses a new edition/build, not in-place mutation.

Extraction preserves PDF page numbers, section headings and stable chunk anchors. Chunking prefers paragraphs and headings, then sentence/newline boundaries with a 1,400-character maximum. Bad signatures, encrypted PDFs, oversized input, and non-extractable content fail closed. Tables are only indexed as their parser-extracted text; clinical review must verify table fidelity before activation.

## Embeddings and PostgreSQL

`EmbeddingProvider` is provider-neutral. The current adapter uses the configured Gemini embedding model, with a separate key from the reasoning provider. `CLINICAL_EMBEDDING_MODEL` must be explicit; no dimension or model is guessed in domain code. Deterministic fakes are used in tests. The chosen key, observed dimension, extraction version, retrieval policy version and build ID are stored for reproducibility. A different embedding configuration requires a new build/edition.

On 2026-09-26, a read-only query of the configured Supabase PostgreSQL reported pgvector **available at version 0.8.0 but not installed**. After the owner confirmed the supplied connection was staging, the Wave 4 migration was applied there once on 2026-09-27; pgvector 0.8.0 is now installed in `extensions`. Production was not touched. The chunk table uses `extensions.vector` without a fixed dimension and a PostgreSQL GIN full-text index. Exact pgvector cosine search is bounded to 12 vector candidates by default. No approximate vector index is created until the embedding dimension, corpus size and query latency justify one. [Supabase extension guidance](https://supabase.com/docs/guides/database/extensions), [pgvector indexing guidance](https://github.com/pgvector/pgvector/blob/master/README.md).

## Hybrid retrieval and sufficiency

Retrieval uses deidentified allowlisted clinical concepts, ACTIVE approved/licensed sources only, jurisdiction/trust/date filters, bounded vector and PostgreSQL full-text candidates, reciprocal-rank fusion, checksum deduplication and at most two chunks per source. Applicable local guidance and trust tier receive priority. Default limits are configurable: 12 vector, 12 lexical, five final items. Similarity is not diagnosis confidence. `SUFFICIENT`, `INSUFFICIENT`, `NONE`, `CONFLICTING` and `STALE` describe evidence availability, not patient risk. Stale-only matches return no old chunks. Material conflicts require explicit reviewer-supplied group/stance metadata; the system does not pretend to detect semantic contradictions automatically.

`EvidenceItem` preserves source/version/chunk IDs, title, organization, jurisdiction, edition/date, section/page/anchor, canonical URL, bounded text and internal rank/build metadata. Only safe source metadata is exposed to patients. Clinical excerpts are fenced as untrusted data; they cannot override safety or establish patient facts. Retrieved text and raw queries are not logged. Retrieval SQL runs in a SAVEPOINT, so pgvector/embedding failure cannot roll back a chat claim or assessment facts; the answer can proceed as UNGROUNDED.

## Interaction integration

At Assessment READY, established fact concepts and the presenting concern form a deidentified query. The final provider receives the evidence bundle separately from patient facts and may return only supplied IDs. The backend rejects invented IDs, provider URLs/source metadata, citation Markdown links and unverified patient assertions. The server rebuilds citation metadata from the bundle. Factual Conversation, medication/guideline questions and lab/multimodal explanations retrieve when clinically relevant; casual chat does not. Conversation preserves the existing provider, memory, quota and safety paths. Missing/insufficient evidence permits a bounded model-knowledge answer without fabricated sources. `grounding_status` is UNGROUNDED, PARTIALLY_GROUNDED or GROUNDED; this operational label is not shown to patients.

Flutter resolves evidence IDs against server-supplied metadata and shows an expandable Sources section only for actually referenced items. It displays title, organization, section/page/date and optional canonical HTTPS link. It does not display IDs, retrieval scores, embedding details or technical RAG terminology. The client rejects unknown IDs and non-HTTPS/credential-bearing/fragment links.

## Tests and evaluation

`backend/tests/fixtures/synthetic_clinical_corpus.json` is explicitly test-only and covers urinary, respiratory, headache, fever, medication, skin, pregnancy, pediatric, conflicting, superseded, withdrawn and injection scenarios. Focused Wave 4 tests cover query deidentification, chunk/page anchors, real PDF extraction where the optional test PDF generator is available, fake embeddings, draft-only ingestion, duplicate checksums, lifecycle closure, hybrid merge, stale/conflict flags, source reference forgery and fail-open Conversation/Assessment. Completion-pass results are recorded below.

Evaluation dimensions for a production clinical corpus remain: retrieval relevance and latency, sufficiency, wrong-source/jurisdiction rate, stale exclusion, citation existence/metadata, claim-to-evidence support, fabricated citation rate, conflict handling and ungrounded honesty. The deterministic synthetic suite exercises contract failures but cannot establish clinical adequacy of a real corpus. Human clinical review and a rights-cleared corpus are required before enabling retrieval for patients.

## Deployment and rollback

Apply Wave 1-3 migrations first, then `add_clinical_knowledge.sql`. Confirm the target PostgreSQL role can create `vector` in `extensions`, and confirm the migration in staging before production. Configure `CLINICAL_EMBEDDING_PROVIDER=gemini`, `CLINICAL_EMBEDDING_MODEL=<approved model>`, optional dimension, and provider credentials. `CLINICAL_KNOWLEDGE_ENABLED` defaults to false. Startup warns if enabled but unconfigured; runtime retrieval fails open to UNGROUNDED. Register, ingest and review real approved documents, activate only after clinical approval, run smoke queries, then enable retrieval. Disabling the flag is the immediate rollback path; historical source/version rows remain intact. No automatic cleanup or source refresh runs. Supersede or withdraw through the CLI.

**Wave 5 blocker:** trusted live web search must not treat its output as curated evidence. It needs separate provenance, licensing policy, URL/domain validation, freshness and citation validation before mixing with this library.

## Completion pass (2026-09-27)

### Regression results

| Check | Final result |
| --- | --- |
| Complete backend `pytest backend/tests` | **379 passed, 7 skipped, 26 subtests passed**. The seven skips require optional local PostgreSQL settings. |
| Focused Wave 4 backend | **24 passed**. |
| Existing AI PostgreSQL integration on disposable localhost PostgreSQL 17 | **5 passed**; server stopped after testing. |
| Complete Flutter `flutter test --no-pub` | **170 passed**. |
| Focused Wave 4 Flutter | **8 passed**. |
| Changed-file `dart analyze` | **No issues found** for the Wave 4 interaction model, bubbles, chat screen and render tests. |
| Full-project `flutter analyze --no-pub` | **Completed with exit 1: 169 project-wide diagnostics** (warnings and info lints). This is not an analyzer pass. Changed Wave 4 files analyze cleanly; unrelated existing lint cleanup was outside this completion pass. |
| `git diff --check` | **Pass (exit 0)**; only Git line-ending conversion warnings. |

### Target database and migration status before staging authorization

At the completion pass, the configured Supabase connection identified only `postgres` database/role on PostgreSQL 17.6, with no reliable staging marker. A read-only query then confirmed pgvector **available 0.8.0, installed: no**, and **zero `clinical_%` tables** in the current schema. The migration was not applied at that time. The owner subsequently confirmed that this connection is staging; the authorized migration and smoke results are recorded below. The disposable local PostgreSQL used for the five existing integration tests has no pgvector package and was not used as a substitute for target validation.

At the completion pass, `CLINICAL_KNOWLEDGE_ENABLED`, `CLINICAL_EMBEDDING_MODEL` and `CLINICAL_EMBEDDING_DIMENSION` were unset in the local backend configuration, so the live provider dimension could not then be measured. The adapter rejects a returned dimension different from its configured output dimension. Ingestion validates vector count, finite values and consistent dimensions; it stores the observed dimension and model/configuration key in each index build. A database trigger rejects a chunk whose `extensions.vector_dims(embedding)` differs from its build, and referenced build key/dimension cannot change. Retrieval validates the query vector, filters on build key and dimension, and fails open to UNGROUNDED if unavailable. No ANN index was added; the initial strategy remains bounded exact similarity. The later real-provider check is recorded below.

Tests establish that disabled retrieval never touches the database; simulated SQL failure rolls back only the retrieval SAVEPOINT, leaving the outer assessment transaction committable; Conversation and Assessment continue with UNGROUNDED responses and no evidence items; unknown/model-supplied citation IDs and URLs are rejected. Flutter omits Sources without validated references. These are deterministic checks, not a substitute for target pgvector integration.

### Historical owner-run staging validation plan

The following was the handoff plan before the owner confirmed staging identity. **It has now been executed and must not be rerun**; the actual outcome follows in the staging activation section.

1. Confirm the intended database is **staging** using an authoritative Supabase project identifier and connection mapping, not the generic database name/role. Confirm Wave 1-3 migrations are already present; do not replay them. Keep patient traffic off the isolated validation database and leave `CLINICAL_KNOWLEDGE_ENABLED=false`.
2. Check `pg_available_extensions`/`pg_extension` and the four `clinical_%` tables. If Wave 4 is not already present, apply `backend/migrations/add_clinical_knowledge.sql` **once** using the staging connection, for example from the repository root with `psql -X -v ON_ERROR_STOP=1 -1 -f backend/migrations/add_clinical_knowledge.sql "$env:STAGING_DATABASE_URL"`. Stop and inspect any partial/previous application rather than blindly rerunning it.
3. Verify pgvector, four tables, the active-version unique index, lexical GIN index and four integrity triggers with these read-only queries:

```sql
SELECT extname, extversion, extnamespace::regnamespace FROM pg_extension WHERE extname = 'vector';
SELECT tablename FROM pg_tables WHERE schemaname = current_schema() AND tablename LIKE 'clinical_%' ORDER BY tablename;
SELECT tablename, indexname FROM pg_indexes WHERE schemaname = current_schema() AND tablename LIKE 'clinical_%' ORDER BY tablename, indexname;
SELECT tgrelid::regclass AS relation, tgname FROM pg_trigger
WHERE NOT tgisinternal AND tgrelid IN (
  'clinical_sources'::regclass, 'clinical_index_builds'::regclass,
  'clinical_document_versions'::regclass, 'clinical_evidence_chunks'::regclass
) ORDER BY relation, tgname;
```

4. On a **non-patient-accessible staging connection only**, run the following smoke data in one transaction. Do not commit it. The three synthetic versions model superseded, withdrawn and active states; uncommitted rows are invisible to other sessions, and `ROLLBACK` removes them. A failure should abort and roll back the transaction, not leave synthetic evidence installed.

```sql
BEGIN;
INSERT INTO clinical_sources (source_id, canonical_title, issuing_organization,
  jurisdiction, source_type, canonical_url, trust_tier, approval_status,
  license_status, license_note, approved_by)
VALUES ('00000000-0000-4000-8000-000000004001', 'Synthetic smoke only',
  'MDQ test', 'NG', 'GUIDELINE', 'https://example.org/smoke', 2,
  'APPROVED', 'APPROVED', 'transactional smoke only', 'staging operator');
INSERT INTO clinical_index_builds (build_id, embedding_key, embedding_dimension,
  extraction_version, retrieval_policy_version, status, completed_at)
VALUES ('00000000-0000-4000-8000-000000004002', 'smoke:3', 3,
  'paragraph-1', 'hybrid-1', 'COMPLETE', now());
INSERT INTO clinical_document_versions (version_id, source_id, edition_label,
  retrieved_at, checksum, status, original_reference, extraction_version,
  index_build_id, chunk_count)
SELECT v, '00000000-0000-4000-8000-000000004001', edition, now(),
  repeat(digest, 64), 'DRAFT', 'synthetic transaction', 'paragraph-1',
  '00000000-0000-4000-8000-000000004002', 1
FROM (VALUES
  ('00000000-0000-4000-8000-000000004003'::uuid, 'old', 'a'),
  ('00000000-0000-4000-8000-000000004004'::uuid, 'withdrawn', 'b'),
  ('00000000-0000-4000-8000-000000004005'::uuid, 'current', 'c')
) AS x(v, edition, digest);
INSERT INTO clinical_evidence_chunks (chunk_id, document_version_id,
  chunk_index, text, embedding, checksum)
SELECT chunk_id, version_id, 0, body,
  CAST(vector_text AS extensions.vector), repeat(digest, 64)
FROM (VALUES
  ('00000000-0000-4000-8000-000000004006'::uuid, '00000000-0000-4000-8000-000000004003'::uuid, 'Old fever guidance', '[0,1,0]', 'd'),
  ('00000000-0000-4000-8000-000000004007'::uuid, '00000000-0000-4000-8000-000000004004'::uuid, 'Withdrawn fever guidance', '[0,1,0]', 'e'),
  ('00000000-0000-4000-8000-000000004008'::uuid, '00000000-0000-4000-8000-000000004005'::uuid, 'Current fever guidance', '[1,0,0]', 'f')
) AS x(chunk_id, version_id, body, vector_text, digest);
UPDATE clinical_document_versions SET status = 'SUPERSEDED'
WHERE version_id = '00000000-0000-4000-8000-000000004003';
UPDATE clinical_document_versions SET status = 'WITHDRAWN'
WHERE version_id = '00000000-0000-4000-8000-000000004004';
UPDATE clinical_document_versions SET status = 'ACTIVE', activated_at = now()
WHERE version_id = '00000000-0000-4000-8000-000000004005';
-- Vector, lexical and hybrid candidates must all contain only the active chunk ...4008.
SELECT c.chunk_id, c.embedding OPERATOR(extensions.<=>)
  '[1,0,0]'::extensions.vector AS distance
FROM clinical_evidence_chunks c JOIN clinical_document_versions v
  ON v.version_id = c.document_version_id
WHERE v.status = 'ACTIVE' ORDER BY distance LIMIT 12;
SELECT c.chunk_id, ts_rank_cd(c.lexical_search_data,
  websearch_to_tsquery('simple', 'fever')) AS lexical_rank
FROM clinical_evidence_chunks c JOIN clinical_document_versions v
  ON v.version_id = c.document_version_id
WHERE v.status = 'ACTIVE' AND c.lexical_search_data @@
  websearch_to_tsquery('simple', 'fever') ORDER BY lexical_rank DESC LIMIT 12;
WITH vector_candidates AS (
  SELECT c.chunk_id, row_number() OVER (ORDER BY c.embedding
    OPERATOR(extensions.<=>) '[1,0,0]'::extensions.vector) AS rank
  FROM clinical_evidence_chunks c JOIN clinical_document_versions v
    ON v.version_id = c.document_version_id WHERE v.status = 'ACTIVE'
), lexical_candidates AS (
  SELECT c.chunk_id, row_number() OVER (ORDER BY ts_rank_cd(
    c.lexical_search_data, websearch_to_tsquery('simple', 'fever')) DESC) AS rank
  FROM clinical_evidence_chunks c JOIN clinical_document_versions v
    ON v.version_id = c.document_version_id WHERE v.status = 'ACTIVE'
    AND c.lexical_search_data @@ websearch_to_tsquery('simple', 'fever')
)
SELECT chunk_id, sum(1.0 / (60 + rank)) AS merged_rank,
  count(*) AS methods FROM (
    SELECT * FROM vector_candidates UNION ALL SELECT * FROM lexical_candidates
  ) ranked GROUP BY chunk_id ORDER BY merged_rank DESC;
-- Expect exactly ...4008 in every query, and methods=2 in the hybrid result.
SELECT b.embedding_key, b.embedding_dimension,
  extensions.vector_dims(c.embedding) AS stored_dimension
FROM clinical_evidence_chunks c JOIN clinical_document_versions v
  ON v.version_id = c.document_version_id JOIN clinical_index_builds b
  ON b.build_id = v.index_build_id;
-- Expect smoke:3, 3, 3 on all three rows.
ROLLBACK;
```

5. In the same isolated environment, exercise the runtime `retrieve_evidence` function with a deterministic three-dimensional fake `EmbeddingProvider` and the same uncommitted transaction/session; check `SUFFICIENT` or `INSUFFICIENT` according to source-diversity policy, exact vector/lexical contribution, active-only returned IDs, and rollback on a deliberately raised SQL error. Do not use a separate connection for uncommitted smoke rows. Then configure the approved real embedding model and verify its returned dimension matches `CLINICAL_EMBEDDING_DIMENSION` when set and the stored build dimension. Do not enable retrieval until this runtime smoke and source governance review pass.

**Historical blocker resolved:** the owner confirmed staging identity, pgvector was installed, and target vector/lexical/hybrid runtime verification passed. Retrieval stays disabled; no real corpus is activated.

## Staging activation (2026-09-27)

The owner explicitly confirmed the supplied Supabase connection is **MDQ+ staging**. Before any write, the connection succeeded to PostgreSQL 17.6 (`postgres` database/role, `public` schema), pgvector 0.8.0 was available but not installed, and no `clinical_%` tables were present. This generic database/role is not itself a staging marker; the owner's confirmation was the authorization. No production connection or patient data was used.

Applied **only** `backend/migrations/add_clinical_knowledge.sql` once in a single transaction, with a successful commit. Post-migration read-only verification found pgvector **0.8.0 installed in `extensions`**, all four Wave 4 tables, 10 indexes including the lexical GIN and unique active-version index, four integrity triggers, 26 constraints, and RLS enabled on all four tables. All four tables had zero rows before the smoke test. No prior migration was replayed.

The rollback-only synthetic smoke used four test sources and five versions (two ACTIVE, one SUPERSEDED, one RETIRED, one WITHDRAWN). It exercised real source registration, ingestion, activation and closure. The deterministic test embedding was **3-dimensional** under key `staging-rollback-smoke:3`; its index builds recorded dimension 3, extraction version `paragraph-1`, retrieval policy `hybrid-1`, and the embedding key. PostgreSQL rejected both a two-dimensional chunk in a three-dimensional build and a referenced build's dimension change. This proves the staging database guard, **not** the actual Gemini provider dimension.

Exact pgvector cosine and PostgreSQL lexical queries each returned the two active synthetic chunks and excluded all three terminal versions. The real `KnowledgeService` returned a bounded two-item `SUFFICIENT` bundle; both items had vector and lexical provenance after merge/deduplication. Evidence IDs, source/version/chunk IDs, titles and editions matched database metadata. Unknown citation IDs and provider-supplied URLs were rejected. The disabled path returned `NONE`; a deliberately failing retrieval SQL query returned `NONE` while its SAVEPOINT preserved the outer transaction. Focused tests separately verify ungrounded Conversation and Assessment results have no Sources and preserve state. No real patient quota was consumed.

The first smoke attempt rolled back after identical synthetic excerpts were deduplicated to one `INSUFFICIENT` item. After making the test excerpts distinct, the corrected smoke passed. The entire successful smoke transaction was rolled back; a separate post-rollback connection confirmed **zero** source, version, build or chunk rows and **zero synthetic ACTIVE sources**. The schema remains installed, but no synthetic or real corpus is active.

Post-migration focused regression: **24 backend Wave 4 tests passed** and **8 Flutter Wave 4 tests passed**. The prior complete backend/Flutter and analyzer results above were not rerun for this staging-only activation.

At the staging migration check, `CLINICAL_KNOWLEDGE_ENABLED` was unset/false and the supplied backend configuration had no embedding model or dimension. No live embedding request was made in that pass. The subsequent embedding activation check below resolved the provider/dimension validation, but retrieval remains disabled until a rights-cleared clinically approved real corpus is activated. Production was not changed.

## Staging embedding activation check (2026-09-27)

The existing `EmbeddingProvider` accepts the exact canonical identifier `gemini`. The supplied local `backend/.env` used for the owner-confirmed staging database is now set to `CLINICAL_EMBEDDING_PROVIDER=gemini`, `CLINICAL_EMBEDDING_MODEL=gemini-embedding-2`, `CLINICAL_EMBEDDING_DIMENSION=1536`, and `CLINICAL_KNOWLEDGE_ENABLED=false`. The existing development Gemini API credential was used; neither the credential nor embedding values were printed. This ignored local configuration is not evidence that any deployed staging service has the same environment. The connected Render workspace did not list an MDQ service, so remote service configuration could not be verified or changed here.

One harmless synthetic text embedding request through the real `GeminiEmbeddingAdapter` succeeded with model `gemini-embedding-2` and requested output dimensionality 1536. Exactly one vector was returned, its measured length was **1536**, and the adapter's configured-dimension validation passed. A first sandboxed attempt failed on a network handshake; the approved-network retry succeeded.

A separate rollback-only staging transaction used the same real adapter for synthetic two-chunk document ingestion and `KnowledgeService` query retrieval. The resulting index build recorded key `gemini:gemini-embedding-2:1536`, embedding dimension **1536**, extraction version `paragraph-1`, and retrieval policy `hybrid-1`; both stored chunks measured 1536 dimensions. PostgreSQL rejected an attempted two-dimensional chunk in that build. The real query returned two bounded evidence items, each selected by both vector and lexical retrieval, with `SUFFICIENT` status and database-backed IDs. The transaction rolled back; a separate connection confirmed **zero** sources, versions, builds, and chunks, and **zero** synthetic ACTIVE sources. No patient data or quota was used.

**Final Wave 4 status:** staging schema, pgvector, integrity guards, real Gemini embedding dimension, and rollback-only hybrid retrieval are validated. Clinical retrieval remains **disabled** (`CLINICAL_KNOWLEDGE_ENABLED=false`); no synthetic or real corpus is active. The remaining patient-retrieval gate is a rights-cleared, clinically approved real source corpus, plus verification of the deployed staging service's configuration before enabling it. Wave 5 was not started.
