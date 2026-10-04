# MDQ+ Curated Clinical Source Intake

No production clinical documents were imported or activated in Wave 4. The test corpus under `backend/tests/fixtures` is synthetic, test-only, and is never loaded by the runtime.

The `docs/clinical_source_intake_manifest.csv` now records seven audited candidates and explicit rights decisions. Two narrowly scoped FDA-authored text pages are classified `VERIFIED_FOR_USE` under FDA's public-domain website policy; that is not clinical approval. All rows remain `NOT APPROVED` and `NOT INGESTED`. The list is not an ingestion queue. The detailed audit and blockers are in `docs/reports/mdq_clinical_corpus_launch_2026-09-27.md`.

## Required intake record

For every real source, the clinical owner must record:

| Field | Required decision |
| --- | --- |
| Canonical title and issuing organization | Exact publication identity; organization approval does not imply every document is approved. |
| Jurisdiction and source type | For example Nigeria national guidance, international guidance, or a selected specialty body. |
| Canonical HTTPS URL or approved local file | Verify that the document came from the stated publisher. Do not scrape a URL as an ingestion shortcut. |
| Edition and publication/effective dates | Use a new edition label for revisions; retain prior editions for audit. |
| License or usage basis and license note | Written permission, public license, or documented internal legal approval for storing/searching the content. |
| Trust tier | 1-3 with documented rationale. |
| Owner and approver | Named internal reviewer accountable for clinical suitability and usage rights. |
| Review cadence | Date or event that triggers freshness review and withdrawal/supersession. |
| Freshness class and review interval | `STABLE`, `STANDARD`, or `SENSITIVE`, with a documented review interval in days. |
| Update-check frequency | Hours between canonical URL checks; checking flags changes but never replaces content. |
| Rights/usage and approval status | Record the actual legal/clinical decision; do not infer permission from a public URL. |
| Conflict notes | Explicit conflict group and stance only after a clinical reviewer identifies material disagreement. |

Registration requires `license_note` and `approved_by`. These are a gate, not proof that the operator actually obtained rights; maintain the evidence of approval outside the database as required by organizational policy. Patient files, including chat-uploaded PDFs, are not eligible curated sources.

## Candidate documents, not approved content

The original five entries remain in the register. WHO's August 2025 malaria edition and NCDC's week 31 report are superseded and must not be ingested. FMOH and NICE need reuse permission; NAFDAC's exact rights remain unresolved. The two FDA patient-safety pages have a reuse basis for FDA-authored text only but await named clinical approval. For current NAFDAC notices, use the [official recalls/alerts index](https://nafdac.gov.ng/category/recalls-and-alerts/) as discovery only and select a specific dated alert before any ingestion. None was registered or ingested.

## Operator sequence

1. Review the document and rights; capture the required intake record.
2. Apply `backend/migrations/add_clinical_knowledge.sql` after Waves 1-3 and configure embedding credentials/model.
3. Run the private `python -m app.tools.clinical_knowledge_cli register ...` from `backend` with explicit freshness class, review interval and update-check frequency, then `ingest --approved-curated-material --source-id ... --edition ... --file ...`.
4. Inspect the resulting DRAFT version, page/section anchors, extracted text and counts. Run `smoke --concepts "deidentified clinical terms"` after activation in a controlled environment.
5. Run `activate --version-id ...` only after human review. To change guidance, ingest a new edition and activate it, which supersedes the active one. Use `retire` or `withdraw` for immediate exclusion from new retrieval.
6. The backend schedules due-source checks daily at 03:15 UTC, guarded by a PostgreSQL transaction advisory lock across workers. An operator can also call the token-protected `/api/v1/internal/clinical/source-updates/check` endpoint or run `check-updates` manually. Review `updates-report` for changed, unavailable, or moved official sources. A check never replaces or activates content. The clinical owner must review any change and ingest/approve a new edition or withdraw the old one.

Do not send patient names, raw messages, or patient documents to the smoke command. Do not activate synthetic fixtures in a patient-accessible database.
