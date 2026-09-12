# Paystack Subscription Renewal Security Audit

Date: 2026-07-13

## Outcome

Automatic Paystack subscription renewals no longer depend on metadata.transactionType. The webhook authenticates the exact raw body, routes by the top-level Paystack event, identifies subscriptions using stored provider identifiers, validates payment integrity, and uses a database-backed event ledger to prevent duplicate fulfilment.

No live Paystack account, remote database, or production customer record was accessed or changed. No secret was exposed, rotated, or written to source.

## Root cause

The previous webhook read the top-level event but still routed fulfilment mainly from the MDQ+ transaction reference and custom metadata. Initial checkout references encode subscription or family_subscription, and the initial charge metadata normally contains user_id. Paystack-generated recurring transactions do not have to retain either representation.

For the observed renewal:

- the recurring transaction reference did not parse as an MDQ+ subscription purchase;
- metadata.transactionType was absent, so it became an empty string;
- invoice.update fell through to the legacy reference router;
- the router acknowledged the request with 200 but returned ignored and logged an unrecognised transaction type;
- no subscription period was changed.

This is consistent with Paystack's documented subscription flow, in which recurring billing produces provider-owned invoice and transaction objects rather than recreating the merchant's original checkout metadata. See the official [webhook documentation](https://paystack.com/docs/payments/webhooks/), [subscription documentation](https://paystack.com/docs/payments/subscriptions/), and [transaction API documentation](https://paystack.com/docs/api/transaction/).

## Files inspected

Principal files inspected during the lifecycle and trust-boundary trace:

- backend/app/api/v1/payments.py
- backend/app/api/v1/subscription.py
- backend/app/api/v1/appointments.py
- backend/app/api/v1/doctors.py
- backend/app/api/deps.py
- backend/app/services/paystack_service.py
- backend/app/services/paystack_amounts.py
- backend/app/services/watchdog_service.py
- backend/app/services/consultation_pricing.py
- backend/app/services/consultation_payout_service.py
- backend/app/models/user.py
- backend/app/models/appointment.py
- backend/app/models/doctor.py
- backend/app/models/consultation_payout.py
- backend/app/models/failed_webhook.py
- backend/app/schemas/user.py
- backend/app/schemas/appointment.py
- backend/app/schemas/doctor.py
- backend/app/core/database.py
- backend/app/core/limiter.py
- backend/app/main.py
- backend/migrations/add_paystack_subscription_fields.sql
- backend/migrations/add_general_queue_payout_ledger.sql
- backend/migrations/add_consultation_refund_workflow.sql
- backend/tests/test_payment_amounts.py
- backend/tests/test_consultation_payout.py
- backend/tests/test_consultation_refund.py
- backend/tests/test_orm_mappers.py
- frontend/lib/src/features/payments/presentation/payment_screen.dart
- frontend/lib/src/features/subscription/presentation/subscription_screen.dart
- frontend/lib/src/core/constants/api_keys.dart

Environment access was reviewed through the modules that read PAYSTACK_SECRET_KEY and related settings. The repository has no separate central Paystack configuration object or migration framework.

## Files changed

- backend/app/api/v1/payments.py
- backend/app/api/v1/subscription.py
- backend/app/models/user.py
- backend/app/models/payment_event.py
- backend/app/models/failed_webhook.py
- backend/app/services/paystack_service.py
- backend/app/services/watchdog_service.py
- backend/migrations/add_payment_event_idempotency.sql
- backend/tests/test_paystack_subscription_webhook.py
- docs/reports/paystack_subscription_renewal_security_audit.md

Pre-existing frontend worktree changes were not modified.

## Previous and new behaviour

| Flow | Previous behaviour | New behaviour |
| --- | --- | --- |
| Initial subscription | Fulfilment depended on the MDQ+ reference and metadata user ID. | Authenticated initialization uses the current user's email and a server-owned plan mapping. A successful charge is validated and sent through the shared subscription processor. |
| Subscription creation | Could grant premium access if the earlier charge was missed. | subscription.create only binds verified provider identifiers and renewal state. It never grants paid entitlement. |
| Automatic charge | A provider reference without MDQ+ metadata was ignored. | A recurring charge with a subscription code is securely recognised and validated as corroborating evidence. |
| Successful renewal | invoice.update fell into the empty transactionType path. | A paid, successful invoice.update is the authoritative period-mutation event. |
| Failed renewal | No reliable subscription routing. | invoice.payment_failed records attention status and invoice/next-payment identifiers without extending or deleting paid access. |
| Disable/not-renew | Identifier lookup and duplicate handling were limited. | Stable identifier lookup, event idempotency, auto-renew disablement, and paid-through access preservation are enforced. |
| Duplicate/companion delivery | Application memory/reference checks could not prevent every double extension. | Unique database event and payment identities prevent replay, concurrency, manual/webhook overlap, and companion-event double fulfilment. |
| Manual verification | Had separate fulfilment branches and risked divergence. | Ownership is checked before the Paystack call, and successful responses use the same payment identity and subscription processor as webhooks. |

## Event-processing design

Routing starts with:

    event_type = payload.get("event")
    data = payload.get("data", {})

Recognised events are charge.success, invoice.update, invoice.payment_failed, subscription.create, subscription.disable, subscription.not_renew, existing transfer events, existing dispute events, and existing refund events.

charge.success is not assumed to be a renewal:

- an MDQ+ subscription reference is an initial purchase and uses shared subscription fulfilment;
- an MDQ+ consultation reference retains the existing appointment validation and fulfilment;
- a charge with a stable subscription code but no MDQ+ payment type is a recurring-charge observation only;
- any other charge is safely ignored.

Unknown top-level events return 200 with an ignored result. Recognised events that fail validation or persistence return a generic 500 after rollback and bounded failure recording, allowing Paystack to retry. Logs contain only the event name, transaction reference, subscription code, customer code, result, and bounded error classification.

## Authoritative renewal event

invoice.update is authoritative for automatic subscription-period mutation because it represents the final subscription invoice state and contains the invoice, transaction, subscription, customer, plan, amount, currency, and next-payment context needed for validation.

A recurring charge.success is corroborating only and never extends access. Therefore:

- charge.success then invoice.update extends once;
- invoice.update then charge.success extends once;
- replayed invoice.update does not extend again.

Initial MDQ+ charge.success remains authoritative for the initial checkout because its MDQ+ reference identifies the intended local purchase. Its payment identity is shared with a later invoice representation so the companion event cannot fulfil it again.

## Signature validation

The webhook:

1. Requires a configured Paystack secret and fails closed with 503 when absent.
2. Rejects declared or actual bodies larger than 256 KiB.
3. Reads request.body() once.
4. Requires x-paystack-signature.
5. Computes HMAC SHA-512 over the exact raw bytes using PAYSTACK_SECRET_KEY.
6. Uses hmac.compare_digest.
7. Parses JSON only after signature validation.
8. Rejects missing/invalid signatures and malformed signed JSON without any database write.

Source IP is not trusted as authentication.

## Subscription identification

Recurring events resolve the local user in this order:

1. paystack_subscription_code;
2. paystack_customer_code;
3. transaction reference through the user/payment-event history;
4. customer email only as a controlled fallback for an existing paid subscription.

Initial events may also use the owner encoded in the server-generated MDQ+ reference. Ambiguous legacy identifier matches fail closed instead of selecting the first row.

The resolved event is then checked against stored customer code/email, plan code, amount, currency, and Paystack test/live environment. Email never overrides a stable identifier.

## Renewal and period calculation

Before fulfilment, the processor requires:

- successful invoice and nested transaction status;
- the expected server-side plan code;
- exact expected amount in kobo;
- NGN currency;
- matching customer identity;
- matching Paystack environment.

The processor records only operational identifiers and timestamps. The next period end uses Paystack's subscription next_payment_date when present and valid, then a reliable provider period end, then the application's calendar-month fallback anchored to the payment time. The fallback adds one calendar month rather than 30 days. An existing later paid-through date is never shortened.

The event claim, subscription mutation, family-dependent mutation, and processed status commit together. On failure the transaction rolls back. A separate bounded failed status is then recorded for retry diagnostics.

## Idempotency design

The new payment_events table stores no webhook body. It has:

- a unique provider plus provider_event_key for exact event replay;
- a unique provider plus payment_key for the same transaction represented by webhook/manual/invoice flows;
- event type, transaction reference, subscription code, invoice code, user ID;
- processing status, timestamps, bounded error code, and short processing note.

Provider keys use the environment, event type, and strongest provider identifier. A SHA-256 raw-body digest is used only when Paystack supplies no stable event identifier. Fulfilment keys use environment plus transaction reference.

The unique constraints are the concurrency boundary. IntegrityError races re-read the winner and return a duplicate acknowledgement. Failed records can be claimed again on Paystack retry. No in-memory cache is involved.

## Database changes and backfill

backend/migrations/add_payment_event_idempotency.sql is additive and repeatable. It:

- adds nullable customer, plan, environment, provider status, last transaction, invoice, period, next-payment, and last-success fields to users;
- adds partial indexes for frequently resolved provider identifiers;
- creates payment_events and its unique constraints/indexes.

No existing column is deleted or renamed. No default fabricates a Paystack identifier.

Backfill procedure:

1. Apply the migration first.
2. Allow verified subscription.create and invoice events to populate real values.
3. Export test and live mappings separately from Paystack.
4. Match an existing account using verified local ownership and provider environment.
5. Populate only real subscription_code, customer_code, and plan_code values.
6. Investigate and resolve duplicates before considering a unique subscription-code index.

The migration deliberately uses a non-unique subscription-code index for backward compatibility. Runtime resolution rejects ambiguous matches.

## Security findings

### Critical

No confirmed Critical finding remained after review.

### High

| Finding | Status | Resolution |
| --- | --- | --- |
| Automatic renewal ignored because fulfilment depended on merchant metadata/reference shape. | Fixed | Top-level event routing, stable identifier resolution, and authoritative invoice processing. |
| No database fulfilment identity covering webhook replay, companion events, manual verification, and concurrent requests. | Fixed | payment_events unique event/payment constraints and atomic claim. |
| subscription.create could grant access without proof of a successful paid transaction. | Fixed | Creation now binds identifiers only. |
| Initialization accepted a client-selected Paystack plan and client email. A substituted provider plan can override transaction amount. | Fixed | Authenticated email, server-owned amount/currency/plan mapping, and client plan mismatch rejection. Live mode requires explicitly configured plan codes. |
| A missing server secret could still be used as an empty HMAC key. | Fixed | Webhook and manual verification fail closed when the secret is absent. |
| FailedWebhook could retain the complete webhook payload, including unnecessary customer/authorization data. | Fixed for new writes | New event ledger is payload-free; DLQ writes contain only four safe identifiers and an error code. Historical rows require operator-led retention cleanup. |

### Medium

| Finding | Status | Resolution or deferral |
| --- | --- | --- |
| Renewal lacked complete amount, currency, plan, customer, and environment checks. | Fixed | Shared validation is required before entitlement mutation. |
| Webhook had no explicit body limit. | Fixed | 256 KiB declared and actual size checks. |
| Recognised processing failures could be acknowledged despite no fulfilment. | Fixed | Rollback, failed event record, generic 500, safe retry. |
| Provider/upstream errors and payout account details could enter logs or client responses. | Fixed | Generic client errors, error-type/classification logging, masked account numbers, and redacted names. |
| Historic failed_webhooks rows may contain old full payloads. | Deferred | Review retention and securely purge/redact according to operational and legal policy. |
| Async routes use synchronous SQLAlchemy sessions. | Deferred | Converting the application's database stack is broader than this payment fix; keep webhook work small and indexed meanwhile. |
| No application-level webhook rate limiter. | Deferred | HMAC and payload limits prevent unauthenticated fulfilment; add proxy-level request limiting only after confirming Paystack delivery/retry allowances. |
| Legacy provider identifiers are nullable and not yet unique. | Mitigated | Ordered lookup and ambiguity rejection; backfill/deduplicate before a later uniqueness migration. |

### Low

| Finding | Status | Resolution or deferral |
| --- | --- | --- |
| Several Paystack logs contained unnecessary business/account names or raw provider messages. | Fixed | Logs now contain operational identifiers and classifications only. |
| A new AsyncClient is created per initialization/verification request. | Deferred | Explicit 15-second timeouts are present. A shared lifespan-managed client can be introduced separately without changing payment semantics. |
| Existing datetime.utcnow calls emit deprecation warnings. | Deferred | Migrate the broader model and test suite to timezone-aware UTC in a dedicated compatibility change. |

### Informational

- Payment initialization and manual verification require authentication and have endpoint rate limits.
- The manual subscription upgrade endpoint is admin-only.
- Subscription cancellation is authenticated and preserves paid-through access.
- The Paystack secret is read from environment and is not returned by the payment routes.
- Existing consultation and payout flows remain distinct from subscription renewal routing.

## Optimisation and reliability findings

Implemented:

- one shared subscription processor for initial webhook, manual verification, and renewal;
- no Paystack network call during a signed webhook;
- no second provider call for companion events;
- indexed stable identifiers and event identities;
- one commit for event claim plus successful entitlement mutation;
- row locking and unique constraints for races;
- calendar-month period calculation without cumulative 30-day drift;
- bounded, structured logging;
- explicit network timeouts and sanitized failure categories;
- retained existing background notification mechanism without moving critical fulfilment out of the transaction.

Deferred:

- a lifespan-managed reusable Paystack HTTP client;
- full conversion from synchronous ORM work inside async routes;
- queue/background webhook processing, because the current app has no durable queue and introducing one was not justified.

## Tests added

backend/tests/test_paystack_subscription_webhook.py contains sanitized fixtures and 30 tests covering:

- signed recurring charge and invoice events;
- absent transactionType;
- initial subscription and consultation compatibility;
- invalid/missing signatures and malformed JSON;
- unknown events;
- duplicate, companion, out-of-order, and concurrent delivery;
- unknown subscription and amount/currency/plan/customer mismatch;
- failed renewal and lifecycle events;
- transaction rollback;
- manual/webhook ordering and ownership;
- test/live separation;
- missing secret;
- server-owned initialization email, plan, amount, and currency.

No real customer data, authorization code, production key, or charge is used.

## Tests and checks executed

| Command/check | Actual result |
| --- | --- |
| backend venv focused suite: python -B -m unittest tests.test_paystack_subscription_webhook tests.test_payment_amounts -v | 33 passed; 146.141 seconds. |
| backend venv final targeted DLQ/rollback rerun | 2 passed; 24.569 seconds. |
| backend venv final full suite: python -B -m unittest discover -s tests -v | 62 passed; 83.947 seconds. |
| PostgreSQL 17 disposable migration check | Migration applied successfully twice; second application reported existing objects skipped; payment_events contained 14 columns. Server stopped and temporary directory removed. |
| Python AST parse with utf-8-sig | Passed for all changed Python source/test files checked. |
| git diff --check | Passed; only Git's existing LF-to-CRLF conversion warnings were printed. |
| Ruff | Not run: Ruff is not installed in the backend virtual environment. |
| mypy | Not run: mypy is not installed in the backend virtual environment. |

An initial command using the machine's default Python could not import firebase_admin, so it did not execute tests. All reported test counts above are from the repository's backend virtual environment. The passing suite emitted existing datetime.utcnow deprecation warnings.

## Remaining risks

- Existing failed_webhooks records may contain historical full payloads and need a controlled retention review.
- Legacy subscriptions need a real-identifier backfill before email fallback can be retired.
- Subscription codes are indexed but not unique until legacy duplicates are audited.
- Proxy-level webhook rate limits and maximum request-body enforcement should also be configured at the deployment edge.
- The application still has synchronous database work in async routes and per-call HTTP clients.
- Paystack plan codes and PAYSTACK_ENVIRONMENT must be correct for each deployment. Test/live datasets and keys must remain separated.
- Failed recognised events require monitoring and reconciliation; they intentionally return 500 so Paystack retries.

## Manual Paystack test-mode procedure

Do not trigger a real charge.

1. Confirm PAYSTACK_SECRET_KEY is a test key and PAYSTACK_ENVIRONMENT is test.
2. Create or identify a test subscription using sanitized test data.
3. Capture the real test subscription code and customer code in the local test record.
4. Serialize a sanitized invoice.update fixture to bytes and calculate x-paystack-signature as HMAC SHA-512 with the test secret. Do not print the secret.
5. POST the exact signed bytes to /api/v1/payments/webhook and confirm one subscription-period update.
6. Replay the identical request and confirm duplicate_event_ignored with no second extension.
7. Send the matching recurring charge.success fixture with no transactionType.
8. Confirm it is recorded as recurring_charge_observed and does not extend again.
9. Repeat in reverse order on a separate fixture and confirm only invoice.update extends.
10. Send the payload with a missing or invalid signature and confirm HTTP 400 with no database write.
11. Send a correctly signed unknown event and confirm HTTP 200 with no entitlement change.
12. Inspect logs and confirm no webhook body, authorization object, card data, email, or secret appears.
13. Inspect payment_events and users to confirm one processed payment identity, provider identifiers, invoice/reference, status, and period timestamps.
14. Send a signed consultation charge fixture and confirm the unrelated appointment payment flow still completes once.

## Deployment considerations

1. Back up the database using the normal operational process.
2. Apply backend/migrations/add_payment_event_idempotency.sql before deploying the application.
3. Set PAYSTACK_SECRET_KEY, PAYSTACK_ENVIRONMENT, PAYSTACK_INDIVIDUAL_PLAN_CODE, and PAYSTACK_FAMILY_PLAN_CODE for the target environment. Live mode deliberately fails closed without explicit live plan codes.
4. Keep test keys, test plan codes, and test subscription rows separate from live values.
5. Deploy the application without changing the Paystack webhook secret.
6. Perform the test-mode manual procedure.
7. Backfill only verified legacy identifiers.
8. Monitor structured result/error_code logs and failed payment_events; reconcile failed recognised events.
9. Configure edge request-size and rate controls without blocking Paystack retries.

## Rollback procedure

1. Roll back the application artifact to the previous known-good version.
2. Leave the additive columns, indexes, and payment_events table in place; old code ignores them and dropping them during an incident adds risk.
3. Do not delete event-ledger rows, because they are needed to reconcile possible duplicate fulfilment.
4. Record the rollback time and manually reconcile signed Paystack invoice/transaction events received during the window before retrying fulfilment.
5. Re-deploy the fixed version after correcting the application issue.

Rolling back the code reintroduces the original automatic-renewal limitation, so it should be a short emergency measure rather than a long-term state.
