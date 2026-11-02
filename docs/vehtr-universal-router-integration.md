# MDQ+ integration with Vehtr's universal Paystack webhook router

This integration is **optional and disabled by default**. The shared routing service is a separate, product-neutral Vehtr Worker; MDQ+ is one independently registered consumer, not the owner of that router. No Paystack URL, MDQ+ payment amount or entitlement is changed by merging this code.

## Compatibility verified against MDQ+ source

- Receiver: `POST https://api.mdqplus.com/api/v1/payments/webhook` as configured by the founder.
- MDQ+ validates the original HMAC-SHA512 signature on **raw request bytes** using its own configured Paystack secret, then uses a database-backed unique payment-event ledger and existing entitlement logic.
- New initial reference prefix `MDQ-`; legacy `MDQ_`. These can be registered with the generic router for **Test** without modifying router code.
- **Consultation payout transfers:** `ConsultationPayout.reference` is generated as `mdq-consult-payout-{appointment_id}` in `backend/app/services/consultation_payout_service.py`, and the Paystack transfer API receives this exact reference. Register `mdq-consult-payout-` as an additional **Test reference prefix** for MDQ+ before routing transfer notifications. This is a product registry setting, not a router code branch. Legacy transfers without such a reference need a verified exact ownership binding; never route a shared `TRF_` prefix globally.
- Recurring invoices and subscription lifecycle events may have Paystack-generated references **without the MDQ prefix**. Register exact `SUB_...` subscription and `INV_...` invoice identifiers from locally persisted, mode-matched records. Never infer ownership from a shared customer code or email.
- The router must preserve unmodified raw body and `x-paystack-signature`; existing MDQ+ verification remains authoritative.

## Optional MDQ+ settings

Install these only after the independent router is deployed, the product is registered, and the Test endpoint has been verified. Supply secrets through the existing secure deployment settings, not source control.

- `VEHTR_PAYSTACK_ROUTER_URL`: router HTTPS origin
- `VEHTR_PAYSTACK_ROUTER_PRODUCT_ID`: registered product ID (e.g. `mdq-plus`)
- `VEHTR_PAYSTACK_ROUTER_PRODUCT_TOKEN`: 32+-character random **product-specific** registration token

With any setting missing, MDQ+ operates as before.

## Automatic bindings and existing subscriptions

After MDQ+ processes a signed webhook or user-authorised verification and commits the existing payment-event record, it queues best-effort registration of the user's **stored** subscription and invoice identifiers. Failure to contact the router never changes whether a Paystack payment was valid or whether MDQ+ delivered the purchased service.

For older subscriptions, the existing MDQ+ API scheduler now supports optional
**automatic Test-only backfill**, avoiding a shell session on Render.
Once the MDQ+ product's securely stored router credential has been configured,
set `VEHTR_PAYSTACK_ROUTER_AUTO_BACKFILL_TEST=true`. The existing backend
runs the Test-only backfill once on service startup and every six hours to
recover transient registration failures. Without that explicit flag **and**
all three `VEHTR_PAYSTACK_ROUTER_*` identity credentials, no job is scheduled.
Registrations are idempotent and only use stored, mode-matched `SUB_` and
`INV_` identifiers; a registration failure does not affect payment acceptance.
Logs show only aggregate counts and outcome, never external identifiers/tokens.

For a one-time manual alternative, run the existing local DB-backed backfill script from `backend/`:

```sh
python scripts/sync_vehtr_router_bindings.py --mode test
python scripts/sync_vehtr_router_bindings.py --mode test --apply
```

The first invocation is **dry-run**. Neither invocation creates Paystack payments or changes subscription entitlements. If there is a registry conflict, fix the authoritative product mapping; never reassign another product's identifiers.

## Cutover

1. Deploy universal Worker+D1 under approved Vehtr Cloudflare infrastructure, with Test enabled and Live disabled.
2. Register MDQ+ and every active product as separate registry entries with unique Test destinations and reference prefixes. MDQ+ requires `MDQ-`, `MDQ_`, and `mdq-consult-payout-` in Test; preserve `enabled_live=false`.
3. Perform and audit the MDQ+ Test-mode backfill of stored subscription identifiers.
4. Test `charge.success`, `subscription.create`, `invoice.update`, `invoice.payment_failed`, recurring charge without MDQ reference, disputes, refunds, duplicate webhooks, unknown/conflicting destinations and temporary downstream outage. Confirm identical original Paystack body/signature and no duplicate grants.
5. Only after both MDQ+ and Yardstick and any other active Paystack integrations work, switch the shared Paystack **Test Webhook URL once** to the Worker. Keep Live Webhook untouched unless separately approved.
6. Monitor quarantined events and replay safely after registering ownership; no default-to-MDQ fallback is permitted.

**Status:** integration branch, review only. Do not deploy, modify Paystack settings or activate Live as part of this PR.
