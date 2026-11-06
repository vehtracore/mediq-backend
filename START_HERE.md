# MDQ+ handover entry point

Documentation review draft, 6 November 2026. Prepared for a documentation-only draft PR; not approved as complete, merged or deployed. This package preserves inspected evidence; it does not replace missing owner decisions or authorize operations.

## Read in order
1. [Product and project context](PRODUCT_AND_PROJECT_CONTEXT.md).
2. [Handover](HANDOVER.md), including the source/tested/deployed distinction.
3. [Sources and checks](SOURCES_AND_CHECKS.md).
4. For actual implementation, inspect the selected checkout and current owner request, then the relevant source and dated report.

Read the [answer-scope verification supplement](ANSWER_SCOPE_VERIFICATION_2026-11-06.md) alongside the clinical activation gate; these are separate acceptance boundaries.

## Verified source checkpoint
Repository: vehtracore/mediq-backend, which contains both backend and Flutter source. Main was re-read on 6 November at **0ae9536273d05de08eee3a33225198009813992b**, committed 3 November 2026 10:15:00 UTC. [Exact commit](https://github.com/vehtracore/mediq-backend/commit/0ae9536273d05de08eee3a33225198009813992b).

The root PROJECT_NEXUS.md contains January-era context and an obsolete-looking narrow profile-upload worklist. Treat it as history, not a verified current roadmap. The former root project_context.md identified another product. This PR replaces it with [MDQ+ context routing](project_context.md); none of the former configuration values are retained or adopted. The Flutter README is a scaffold README, not a setup or product specification.

## Deletion gate
Do not infer that all old-chat decisions are preserved. Preserve open product and operational questions as open items; completing them is not required to delete independently preserved redundant text chats. Before deleting any chat, verify its unique decision/context and attachment coverage and obtain separate user approval.
