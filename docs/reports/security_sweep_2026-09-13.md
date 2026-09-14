# MDQ+ Security Sweep — 2026-09-13

## 1. Executive Security Result

The sweep found 1 Critical, 4 High, 4 Medium, and 3 Low issues.

| Severity | Found | Fixed in code | Remaining / deployment-gated |
|---|---:|---:|---:|
| Critical | 1 | 1 | 0 |
| High | 4 | 4 | 0 |
| Medium | 4 | 2 | 2 |
| Low | 3 | 0 | 3 |

No demonstrated unauthenticated clinical-data read, cross-patient Vault read, cross-consultation chat/video access, unsigned financial mutation, or committed live secret remains in the reviewed code. Three migrations were created and were not executed. Until they are applied, one-time family invites and payload-bound emergency idempotency must not be deployed, and the Realtime former-participant restriction is not active in the database.

Security-required behavior change: patient signup provisioning and doctor registration now require the Supabase access token created by `signUp`. If staging is configured to require email confirmation and therefore returns no session at signup time, local provisioning must occur after confirmation/sign-in; an unauthenticated fallback must not be restored.

The complete route-by-route inventory is in [security_authorization_inventory_2026-09-13.md](/C:/Users/HP/Desktop/mediq_app/docs/reports/security_authorization_inventory_2026-09-13.md).

## 2. Authorization Architecture

Supabase is the authentication authority. The backend verifies the JWT signature through the project JWKS, pins ES256, validates audience, issuer, expiry, immutable `sub`, and signed email. Local account resolution is now by `users.supabase_auth_id`; email is used only for a one-time migration bridge when exactly one unbound local row matches. Client role and identity claims are never authoritative.

Role checks occur server-side at each privileged route. Patient appointment mutations bind `appointment.patient_id` to the current user. Doctor consultation mutations resolve an active, verified doctor row from the current user and bind `appointment.doctor_id` to that doctor. Admin routes derive the admin from the authenticated local role. Resource lookups for Vault, summaries, notification IDs, payment references, support requests, device installations, temporary images, and consultation rooms include ownership or membership constraints.

Presence is UX-only. HTTP, WebSocket, video, and database Realtime policies independently evaluate consultation membership. Payment entitlement is granted only from server/provider state. Provider-cost operations use server-derived identity plus quotas, rate limits, idempotency or in-flight controls as applicable.

## 3. Historical Finding Re-check

| Earlier concern | Current status | Evidence / action |
|---|---|---|
| Cross-user access paths | Fixed | Vault, AI, notification, payment, support, device-token and consultation queries are owner/member scoped; negative tests pass. |
| Chat history by appointment ID | Fixed | `require_consultation_access` is called before message lookup. |
| Arbitrary WebSocket room joins | Fixed and hardened | JWT first-frame auth, path-user equality, appointment membership, per-message recheck, expiry close and message cap. |
| Doctor queue exposing unassigned patient data | Fixed | General queue returns no patient ID/name/history; only bounded submitted triage text. |
| Missing doctor assignment checks | Fixed | Assigned-doctor guard covers accept/decline/cancel/complete/prescribe/refer/video/chat; stale doctor-row role bypass was closed. |
| Admin-like subscription upgrade | Fixed | `/subscription/upgrade` requires admin and changes only the authenticated admin row. Provider events remain the production upgrade path. |
| Unauthenticated slot creation | Fixed | Valid JWT plus owning approved doctor or admin delegation is required. |
| Unauthenticated payment initialize/verify | Fixed | Both require auth and validate reference owner before a Paystack call; webhook is intentionally public but HMAC-authenticated. |
| Cloudinary/public upload | Partially fixed | Auth, fixed client namespace, file signatures and size/type gates are enforced. Public delivery remains an architectural privacy risk. |
| AI summary access | Fixed | Read/update/delete/continue/export bind summary IDs and versions to current user. |
| Emergency behavior ambiguity | Fixed and hardened | Nearby search remains independent of paid SMS; SMS uses current profile/NOK/entitlement and atomic quota/cooldown. Payload-bound replay needs the new migration before deployment. |
| Role trust in request payloads | Fixed | Signup requires a verified Supabase identity, forces patient, and forbids overposted role/plan fields. Doctor onboarding is separately authenticated and remains pending. |

## 4. Findings

### Critical — fixed

1. `POST /auth/signup`: an unauthenticated caller could provision a local account with a client-supplied role. Because account lookup was email-based, a matching Supabase login could acquire that local role. Root cause: provisioning was outside the JWT boundary and `UserCreate.role` was trusted. Fix: require a verified Supabase identity, bind immutable `sub`, require signed-email equality, force `patient`, and forbid role/plan overposting. Regression tests cover admin-role payloads, mismatched email, immutable-sub lookup, bound-row takeover, and expired tokens.

### High — fixed

1. `GET /doctors/` and `GET /doctors/{id}` returned the full doctor schema publicly, including license/document URLs, bank details, and Paystack identifiers. Fix: a public schema now exposes only booking-profile fields and individual reads require a verified doctor. Test: private fields are absent from serialization.
2. Doctor queue/request/appointment routes could rely on the existence of a doctor row without consistently checking the authenticated role and approval state. A stale/inconsistent doctor row could cross the intended role boundary and reveal assigned clinical context. Fix: the shared guard now requires active user role `doctor`, verified doctor, and active status; all doctor list/queue routes use it. Tests cover a patient with a stale doctor row and a pending doctor.
3. Upload endpoints accepted a claimed MIME type or extension without validating bytes, allowed a caller-selected Cloudinary namespace, allowed PDFs through profile-image routes, and lab analysis read an unbounded body before provider work. Fix: magic-signature validation, 5 MiB bounded reads, image-only profile/general routes, fixed general namespace, and lab signature/size validation. Tests cover spoofed script content, PDF rejection, and removal of folder control.
4. A family invite JWT was reusable by multiple accounts until capacity/expiry, allowing a leaked token to grant Family entitlement repeatedly. Fix: random one-time nonce stored on the primary, row-locked comparison, expiry, and atomic consumption; generating a new invite invalidates the old outstanding invite. Test covers a successful join followed by replay from another account.

### Medium

1. WebSocket tokens were checked only during handshake, so a socket could survive token expiry; message debug logging included content prefixes and frames had no route-level size cap. Fixed with a 10-second auth deadline, token-expiry timeout/close, 8 KiB limit, server-derived sender, and metadata-only logs. Tests cover claimed-identity mismatch and unrelated membership.
2. Emergency idempotency treated same key/different alert details as a duplicate rather than a conflict. Fixed in code with a user/server-payload fingerprint and 409 conflict. The database column migration must be applied before this backend is deployed. Regression test passes.
3. Realtime presence membership did not exclude completed, cancelled, unpaid or otherwise inactive former consultations. A tightening migration now requires `confirmed` and `paid`; it remains deployment-gated until applied and public Realtime access is disabled. Policy test verifies the SQL predicate.
4. Cloudinary assets are still publicly addressable by URL. Application routes no longer expose doctor document URLs publicly and client folder selection is gone, but possession of an existing URL can bypass application authorization. Remaining architectural risk: sensitive documents/lab images should move to authenticated or signed/private delivery with explicit retention/deletion.

### Low — remaining bookmarks

1. CORS permits `*` origins with credentials disabled. This is not a cookie-auth bypass because the API uses explicit bearer tokens, but production web origins should be allowlisted.
2. Trusted-host middleware is not configured. Add production hostnames at deployment after confirming Render/custom domains.
3. Doctor preflight intentionally remains public and can reveal email/license registration conflicts. It is rate-limited and does not mutate state; use a generic response/CAPTCHA if enumeration becomes an observed abuse vector.

## 5. Cross-User / IDOR Results

| Area | Result |
|---|---|
| Vault | Own-patient filters on history, export and both delete paths; cross-user UUID tests deny access. |
| AI | Saved source summaries are owner/version bound; generated owner/provenance fields are not client fields; user-bound idempotency prevents cross-user result replay. |
| Consultation | Patient owner or assigned approved doctor only across HTTP, chat, WebSocket and video. Unrelated Patient B and Doctor B are denied. |
| Notifications | List/count/read/read-all bind current user; notification substitution returns 404. Device installations/tokens have one current owner. |
| Family | Signed, expiring, one-time invite; primary/capacity/plan rechecked under row lock; unrelated family IDs are not accepted. |
| Payments | Initialize/verify reject another user's reference before provider calls; webhook signature and authoritative transaction fields are mandatory. |
| Support | No read/status-by-ID route exists; authenticated identity supplies email/name/role; request ID replay cannot return another user's result. |
| Uploads | Auth and content checks pass; no private authenticated retrieval route exists. Public Cloudinary URL risk remains. |

## 6. Consultation Security

- HTTP: `require_consultation_access` and appointment-specific patient/doctor guards bind both role and relationship. Paid/active/time-state checks are separate from presence.
- WebSocket: auth is required before join, user identity cannot be claimed in the path/frame, membership is checked at join and again before persistence, token expiry closes the socket, and malformed/oversized frames fail safely.
- Video: appointment membership selects stable channel-local UID; the client cannot request the other participant's UID; expiry is bounded by consultation end.
- Realtime presence: `auth.uid()` maps to unique `supabase_auth_id`; only patient/assigned doctor, `confirmed`, and `paid` pass after migration. Metadata grants no HTTP/WS/video capability.

## 7. Role / Privilege Enforcement

Patients cannot call approved-doctor or admin operations. Approved doctors can act only on assigned/requested consultations and their own payout/profile data. Admin/system-like payout, refund, doctor approval, content mutation and manual subscription override routes require the local admin role derived from the verified Supabase subject. Normal authenticated 403 responses do not become authentication failures; pending doctors now receive 403 rather than an invalid-token 401.

## 8. Financial / Entitlement Security

Paystack initialization ignores body email, derives user email, validates reference owner, expected appointment amount/type/state, configured subscription amount and plan code. Manual verification repeats ownership checks before contacting Paystack and reuses the authoritative processing path. Webhooks require raw-body SHA-512 HMAC, bounded body, environment/currency/amount/plan/reference checks, and durable event idempotency. Payout/refund decisions are admin-only and audited.

Premium AI continuation/summary save, Family access, Emergency SMS, lab image allowance, heavy AI usage, STT and TTS quotas are calculated from the authenticated database row. Expired subscriptions are lazily downgraded by the authentication dependency before route logic. Flutter visibility is not an enforcement boundary.

## 9. Provider Abuse Controls

- AI: authentication, consent, per-IP route limits, per-user in-flight lease/replay guard, burst cap, plan quota, heavy-attachment quota and bounded uploads.
- STT: type/size/duration validation before provider submission, user/IP limits, one-in-flight guard, user-bound reservation ledger, exactly-once finalization/refund and stale recovery.
- Emergency SMS: stored NOK/profile identity, paid entitlement, user-bound fingerprinted request, atomic monthly quota/cooldown, and provider-result finalization.
- Support: authenticated identity, bounded body, 10/hour limit, durable unique request, atomic send claim and stale retry recovery; message bodies are not logged.
- Notifications: token/installation reassignment is atomic; logout unregisters only the authenticated installation; push payload navigation never grants resource access.

## 10. File / Media Security

JPEG, PNG, WebP and PDF types are recognized by content signatures; profile/general uploads accept images only. Uploads read at most 5 MiB plus one byte. The generic client cannot select doctor-license or certificate folders. AI images use a user-prefixed temporary public ID and scheduled deletion; AI PDFs are transient. Lab images remain stored in Cloudinary and doctor onboarding documents use public Cloudinary delivery, so signed/private delivery and explicit deletion remain architectural follow-up work.

## 11. Deployment Security

- CORS: wildcard origin, credentials disabled; allowlist production web origins before launch.
- Secrets: no tracked `.env`, provider secret, service-account file, or live Paystack/OpenAI key was found. Local `backend/.env` is ignored and values were not printed. Firebase client configuration is also ignored. Do not rotate anything based on this sweep.
- Debug/docs: FastAPI Swagger and ReDoc are disabled; no application debug mode is enabled in `main.py`.
- Secret loading: Paystack, OpenAI/Gemini, Termii, Resend, Cloudinary, Firebase and Supabase privileged credentials are server environment values. Avoid enabling the diagnostic email endpoint in production.
- Separation: explicit production host/CORS configuration is still required; service startup currently does not enforce an environment-specific allowlist.
- Realtime: apply both presence migrations in order, release private-channel clients, then turn Supabase Realtime public access OFF and run the staging checks below.

## 12. Migrations

No migration was executed.

1. `add_one_time_family_invites.sql`: adds nonce/expiry columns and a partial unique index. Apply before deploying the family backend changes.
2. `add_emergency_sms_request_fingerprint.sql`: adds the non-sensitive SHA-256 fingerprint column. Apply after `add_emergency_sms_request_idempotency.sql` and before deploying the emergency backend changes.
3. `tighten_private_consultation_presence.sql`: replaces the existing membership function to require confirmed, paid consultations. Apply after `add_private_consultation_presence.sql`.

Recommended staging order: database backup/checkpoint; apply the three migrations in the dependency order above; deploy backend; deploy/confirm private Realtime client; turn public Realtime access OFF; execute the matrix below. Roll back the backend before reversing columns; the Realtime function can be replaced with its prior definition if rollback is required.

## 13. Tests

Command:

```powershell
cd C:\Users\HP\Desktop\mediq_app\backend
$env:PYTHONDONTWRITEBYTECODE='1'
venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
```

Result: **256 passed, 24 subtests passed, 0 failed** in 290.20 seconds. There were 75 pre-existing deprecation warnings. `git diff --check` passed. No frontend file was changed by this sweep.

After the final approved-doctor booking guard was tightened, the directly affected appointment/security suite was rerun: **45 passed, 0 failed** in 68.92 seconds.

```powershell
venv\Scripts\python.exe -m pytest tests/test_security_sweep.py tests/test_consultation_timing.py tests/test_consultation_chat_video.py tests/test_notifications.py -q -p no:cacheprovider
```

The suite includes negative authorization coverage for unauthenticated protected mutation, role overposting, signed identity mismatch, immutable-sub account isolation, stale/pending doctor privilege denial, unrelated patient/doctor consultation access, WebSocket identity/membership denial, video denial, Vault/AI owner substitution, notification IDOR, payment reference ownership, Free entitlement, emergency identity/quota/replay, support identity/idempotency, family replay, invalid uploads, and admin rejection.

## 14. Manual Staging Security Tests Required

### Auth

1. Call `/auth/me` with malformed and expired tokens; expect 401 with `WWW-Authenticate`.
2. Use a valid patient token with signup body role `admin` or a different email; expect 422/403 and no row/role change.
3. Test both Supabase email-confirmation configurations. If `signUp` returns no session, confirm provisioning resumes only after the user verifies and signs in.
4. Trigger an authenticated forbidden action; expect 403 and confirm the app keeps the session.
5. Log A out and B in on the same device; `/auth/me` must resolve B by Supabase `sub`, never A by stale email/session data.

### Consultation

1. Create paid confirmed appointment X for Patient A and Doctor A; verify history, WS and video work for both.
2. With Patient B, substitute X in chat history, WS path and video token; expect 403/close 4403.
3. Repeat with Doctor B; expect denial.
4. Send a WS auth frame claiming A's path user from B's token; expect 4403. Leave a valid socket open past a short-lived token expiry; expect 4401 and successful reconnect only with a refreshed token.
5. Mark X completed; HTTP/video must close according to product rules and Realtime presence subscription must fail after the tightening migration.

### Vault / AI

1. Save records for A. With B, substitute A's summary/record UUID in continue, save-source, export and both delete routes; expect 404/403 and no mutation.
2. Reuse A's AI request key as B; B must not receive A's result. Reuse same key/same payload as A safely; change payload and expect 409.
3. Call Premium-only continue/save as Free; expect entitlement denial. Confirm temporary PDF/image bytes are deleted/not persisted as documented.

### Payment

1. Initialize and verify A's reference as B; expect 403 before any Paystack request.
2. Tamper email, amount, appointment ID, user ID, transaction type and plan code; expect denial and no entitlement/payment mutation.
3. Replay the same signed webhook/reference; verify one financial/entitlement transition. Change body without recalculating signature; expect rejection.

### Emergency

1. Call SMS directly as Free; expect logged response and no Termii request. Nearby services must still work.
2. As paid A, verify the SMS name and NOK come from A's stored profile; overpost user/NOK/quota fields and expect 422.
3. Replay the same request ID/payload; no second SMS/quota use. Change coordinates/address under the same ID; expect 409. Send concurrent distinct IDs; only atomic cooldown/quota winners queue.

### Family

1. Generate invite for Family primary A and redeem once as B.
2. Replay the same token as C; expect 400. Generate a new token and verify the old outstanding token is invalid.
3. Downgrade/expire A before redemption and attempt join; expect 403. Try unrelated family IDs without a valid token; expect denial.

### Notifications

1. Register A's installation/token, log out, log B in, and claim the same installation/token; confirm exactly one owner and that A pushes do not arrive for B.
2. Fetch/mark A's notification UUID as B; expect 404. Confirm navigation to A's appointment still fails resource authorization.

### Support

1. Add email/name/role/Reply-To fields to the body; expect 422 and verify the delivered message uses authenticated profile identity.
2. Reuse the same request ID and payload; expect safe replay. Change payload or use the same key from another user; expect conflict and no disclosure.

### Files / Realtime / deployment

1. Upload script/SVG bytes named `.png`, PDF bytes to profile upload, oversized image, traversal folder and doctor-license folder; expect denial before Cloudinary/provider calls.
2. Confirm public doctor responses contain no document, bank-account or Paystack identifiers.
3. Apply the Realtime migrations, verify A/Doctor A presence, then turn public access OFF; Patient B, Doctor B, completed X and unpaid rooms must not subscribe.
4. Confirm production docs remain disabled, diagnostic email endpoint returns 404, CORS allows only the eventual approved web origins, and Host-header tests match the configured trusted hosts once added.

## 15. Remaining Risks / Bookmarks

Accepted architectural risks for review: Cloudinary URLs are bearer-like public URLs; lab images and onboarding documents are not delivered through an authenticated download boundary.

Production deployment tasks: apply the three migrations before backend deployment; disable Supabase Realtime public access after private-client validation; configure explicit CORS origins and trusted hosts; verify a 32-byte-or-longer Family invite `SECRET_KEY`; keep diagnostic email disabled.

Future hardening: signed/private Cloudinary delivery with retention/deletion; generic doctor-preflight responses or CAPTCHA; distributed/global rate limiting where the current limiter or in-memory fallbacks are per process; periodic access review for admin accounts and provider credentials.

## 16. Files Changed

Security implementation:

- `backend/app/api/deps.py`
- `backend/app/api/v1/auth.py`
- `backend/app/api/v1/appointments.py`
- `backend/app/api/v1/chat.py`
- `backend/app/api/v1/chat_socket.py`
- `backend/app/api/v1/doctors.py`
- `backend/app/api/v1/emergency.py`
- `backend/app/api/v1/family.py`
- `backend/app/api/v1/lab.py`
- `backend/app/api/v1/media.py`
- `backend/app/api/v1/upload.py`
- `backend/app/models/emergency_sms_request.py`
- `backend/app/models/user.py`
- `backend/app/schemas/doctor.py`
- `backend/app/schemas/user.py`
- `backend/app/services/media_service.py`

Migrations/tests/reports:

- `backend/migrations/add_emergency_sms_request_fingerprint.sql`
- `backend/migrations/add_one_time_family_invites.sql`
- `backend/migrations/tighten_private_consultation_presence.sql`
- `backend/tests/test_consultation_realtime_policy.py`
- `backend/tests/test_emergency.py`
- `backend/tests/test_notifications.py`
- `backend/tests/test_security_sweep.py`
- `docs/reports/security_authorization_inventory_2026-09-13.md`
- `docs/reports/security_sweep_2026-09-13.md`

No dead-code, schema-cleanup, repository-cleanup, UI redesign, dependency modernization, or general lint work was started.
