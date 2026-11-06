# MDQ+ product and project context

Evidence-backed draft, 6 November 2026. Source checkpoint: **0ae9536273d05de08eee3a33225198009813992b**. This is a reconstruction of inspected implementation and reports, not an invented complete PRD.

## Product identity and scope
The historical PROJECT_NEXUS identifies MedIQ (MDQ+) as a telehealth mobile product for finding doctors, booking video consultations and AI symptom checking. Current registered backend routers demonstrate a much broader implemented surface: authentication, doctor verification/discovery, appointments, consultation chat/video, AI consent and assistance, lab analysis, personal Vault, voice, family plans, emergency support, notifications, payments/subscriptions, reviews/content, support and administration. Router presence establishes source scope, not release readiness or verified live availability.

The repository holds Flutter client code and a FastAPI/SQLAlchemy backend. Supabase-verified identity is resolved to a local account using supabase_auth_id. The inspected authorization inventory distinguishes patients, approved doctors and administrators; ownership and entitlement checks belong on the server. The current identity dependency and route registration source are the implementation anchors.

## Principal journeys represented in the evidence
- Patient: authenticate, find a verified doctor, select availability or request/queue a consultation, pay, participate in the authorized chat/video session, and retain/review personal records.
- Doctor: complete verification, manage permitted professional/availability information, accept or claim eligible consultations, deliver the assigned consultation and enter the controlled completion/payout workflow.
- Administrator: review doctor verification, account status, consultation payout/refund review and operational information through authenticated administrative routes.
- AI: consent-gated assistance and document/image/voice processing with server-owned quotas and evidence controls. Patient clinical retrieval activation remains a separate gate.

These summarize implementation evidence. Exact current pricing, plan catalogue, launch territories, availability promises, clinical ownership, service-level commitments and feature-by-feature owner acceptance are **not established by this draft**.

## Consultation and payment boundaries
The September financial lifecycle report separates payment, consultation completion, payout obligation, complaint/refund review, admin approval and external financial action. Completion does not itself approve a payout. It records a 24-hour hold after the consultation/session grace timing, refund/payout mutual exclusion and PostgreSQL row-locking requirements. Treat timing and eligibility as source-backed historical contracts requiring current source review before changes, not newly approved business policy.

The November router integration is optional and default-off. The product remains responsible for raw-body Paystack HMAC verification, authoritative payment validation and idempotent entitlements. Shared Vehtr infrastructure only routes events. Exact subscription/invoice bindings must derive from stored, mode-matched identities; shared customer identity is not product ownership. Test and Live backfill flags are independent and do not enable payments or global Live ingress. The same receiver's simultaneous acceptance of both environments is explicitly unverified.

## Clinical knowledge safety gate
The clinical corpus report's final 28 September closure takes precedence over older optimistic milestones in the same file: **not accepted for activation**, patient retrieval flags remain false in the recorded local/staging checkpoint. It records failed live Nigerian discovery, two degraded answers in a 15-case review (13 pass / 2 fail), and no conditional enabled staging API acceptance. Fixture discovery success is not live-search acceptance. Current hosted flag state was not queried for this draft. Do not enable retrieval based on passing unit tests or historical Wave 5 web smokes.

## Canonical evidence routes
- [Current backend route registration](https://github.com/vehtracore/mediq-backend/blob/0ae9536273d05de08eee3a33225198009813992b/backend/app/main.py).
- [Current identity dependency](https://github.com/vehtracore/mediq-backend/blob/0ae9536273d05de08eee3a33225198009813992b/backend/app/api/deps.py).
- [Authorization inventory, dated 13 September](https://github.com/vehtracore/mediq-backend/blob/0ae9536273d05de08eee3a33225198009813992b/docs/reports/security_authorization_inventory_2026-09-13.md).
- [Consultation financial lifecycle](https://github.com/vehtracore/mediq-backend/blob/0ae9536273d05de08eee3a33225198009813992b/docs/reports/consultation_financial_lifecycle_2026-09-16.md).
- [Final clinical activation report](https://github.com/vehtracore/mediq-backend/blob/0ae9536273d05de08eee3a33225198009813992b/docs/reports/mdq_clinical_corpus_launch_2026-09-27.md).
- [Universal router integration](https://github.com/vehtracore/mediq-backend/blob/0ae9536273d05de08eee3a33225198009813992b/docs/vehtr-universal-router-integration.md).

## Information still needed from preserved context
An approved product requirements baseline and exclusions; latest owner priorities; an authoritative roadmap and acceptance register; current deployed app/schema/environment mapping; provider and data ownership; secure recovery locations; current design approval and unique asset provenance. Keep secret values and personal clinical data out of these documents.
