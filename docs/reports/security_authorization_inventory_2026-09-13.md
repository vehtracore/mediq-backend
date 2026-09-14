# MDQ+ Authorization Inventory — 2026-09-13

This inventory covers the active routers included by `backend/app/main.py` under `/api/v1`. `Any` means any valid local MDQ+ account; `P`, `D`, and `A` mean patient, approved doctor, and admin. `Self` means identity is derived from the verified Supabase JWT rather than a client identity field. `Sensitive` includes private, clinical, financial, or provider-cost data.

## Authentication and account

| Method/path | Auth / roles | Ownership / entitlement | Client identifiers and server verification | Idempotency / rate limit | Sensitive |
|---|---|---|---|---|---|
| `GET /auth/test-email/{email}` | Public, disabled unless explicitly configured | Diagnostic only | Client email; delivery allowlist/cap | Email guard + 2/hour | Email/provider cost |
| `POST /auth/signup` | Verified Supabase JWT; P only | Self | Body email must match signed email; immutable `sub` stored; body role fixed to patient | Same `sub` replay returns same row; 20/hour + 3/minute | Profile |
| `POST /auth/doctor/preflight` | Public | No mutation; registration availability only | Client email/license checked for conflicts | 10/minute | Account-existence signal |
| `POST /auth/doctor/register` | Verified Supabase JWT; creates pending D | Self; no approval granted | Body email must match signed email; immutable `sub` stored; documents signature/size checked | Same authenticated application returns existing row; 5/hour + 2/minute | Verification documents |
| `GET /auth/me` | Any | Self | No client identity | Read-only | Full own profile |
| `PUT /auth/me` | Any | Self | Explicit allowlisted fields; role/plan/admin fields forbidden | Not idempotency-keyed | Medical/profile |
| `GET /auth/my-doctor-profile` | D | Self doctor row | Doctor resolved from current user | Read-only | Own professional/payout profile |
| `GET /auth/verify-email` | Public signed legacy token | Token-bound account | Opaque verification token checked and cleared | Replay becomes invalid | Account state |
| `POST /auth/admin/approve-doctor/{doctor_id}` | A | Admin decision | Doctor ID looked up; admin derived from JWT | State converges; no key | Verification state/doc context |
| `POST, PUT, PATCH /auth/me/device-token` | Any | Self installation | User from JWT; installation/token atomically reassigned | Upsert; token/installation unique | Push routing |
| `DELETE /auth/me/device-token` | Any | Self installation | Both authenticated user and installation must match | Safe replay | Push routing |
| `DELETE /auth/me/deactivate` | Any | Self | No client identity | Repeated call blocked by inactive-account auth | Full account state |

## Appointments and consultation workflow

| Method/path | Auth / roles | Ownership / entitlement | Client identifiers and server verification | Idempotency / rate | Sensitive |
|---|---|---|---|---|---|
| `POST /appointments/slots` | Approved D or A | Doctor owns target; A may delegate to active doctor | Client doctor ID resolved and ownership checked | No key | Availability |
| `GET /appointments/doctors/{doctor_id}/slots` | Public | Verified doctor availability only | Doctor ID scopes unbooked slots | Read-only | No |
| `DELETE /appointments/slots/{slot_id}` | Approved owning D or A | Slot owner/delegated admin | Slot and doctor relationship checked | Safe only before booking | Availability |
| `POST /appointments/book` | P | Self; selected live doctor slot | Slot ID locked by uniqueness; price from doctor record | Slot uniqueness; no rate decorator | Clinical notes/financial |
| `POST /appointments/book-general` | P | Self | Patient from JWT; server price/type/reference | No key/rate decorator | Triage/financial |
| `POST /appointments/request` | P | Self; active requested doctor | Doctor ID verified; server rate; per-user pending caps | Returns existing same pending request | Triage/financial |
| `GET /appointments/my` | P | Patient-owned rows only | No client user ID | Read-only | Consultation/payment |
| `PUT /appointments/{appt_id}/pay` | Any authenticated | Always returns 410; cannot mutate payment state | Appointment ID unused | Safe denial | No |
| `PUT /appointments/{appt_id}/cancel` | Owning P | Patient-owned appointment | Appointment ID + `patient_id == current_user.id` | State guarded | Consultation/payment |
| `GET /appointments/doctor/requests` | Approved requested D | Assigned VIP requests only | Doctor derived from JWT and appointment assignment | Read-only | Triage/history for specifically requested doctor |
| `GET /appointments/doctor/queue` | Approved D | Unassigned, paid GP queue | No patient ID returned; only bounded triage text | Read-only | Minimal triage |
| `PUT /appointments/doctor/queue/{appt_id}/claim` | Approved available D | Atomic claim of eligible paid unassigned GP | Appointment type/status/payment/assignment checked in conditional update | Atomic single winner | Triage becomes assigned consultation |
| `PUT /appointments/doctor/appointments/{appt_id}/accept` | Assigned approved D | Requested appointment only | Doctor/appointment relationship checked | State guarded | Consultation |
| `PUT /appointments/doctor/appointments/{appt_id}/decline` | Assigned approved D | Requested appointment only | Relationship/status checked | State guarded | Consultation |
| `PUT /appointments/doctor/appointments/{appt_id}/cancel` | Assigned approved D | Assigned appointment only | Relationship/timing checked | State guarded | Consultation |
| `PUT /appointments/doctor/appointments/{appt_id}/complete` | Assigned approved D | Paid, started assigned consultation | Relationship/status/payment/attendance checked | State guarded | Clinical/financial |
| `PUT /appointments/doctor/appointments/{appt_id}/prescribe` | Assigned approved D | Assigned appointment/record | Relationship checked before write | Update converges; no key | Clinical |
| `POST /appointments/doctor/appointments/{appt_id}/refer` | Assigned approved D | Assigned appointment | Relationship checked before write | No key | Clinical |
| `GET /appointments/doctor/appointments` | Approved D | Assigned confirmed appointments only | Doctor derived from JWT | Read-only | Clinical/history |
| `PATCH /appointments/{appt_id}/acknowledge` | Owning P | Patient-owned appointment | Relationship/status checked | Boolean converges | Consultation |
| `PATCH /appointments/{appt_id}/propose` | Requested approved D | VIP doctor specifically requested | Relationship/type/status/payment checked | State guarded | Consultation |
| `POST /appointments/{appt_id}/complaint` | Owning P | Own completed paid consultation | Ownership, hold window, existing dispute checked | One complaint per appointment | Clinical/financial |
| `POST /appointments/referral` | Assigned approved D | Assigned appointment | Relationship checked; recipient/body supplied by doctor | Email guard + 5/hour | Clinical email/PDF |

## Consultation transport

| Method/path | Auth / roles | Ownership / entitlement | Client identifiers and server verification | Idempotency / rate | Sensitive |
|---|---|---|---|---|---|
| `GET /p2p/test` | Public | Diagnostic only | None | Read-only | No |
| `GET /p2p/history/{appointment_id}` | P owner or assigned D | Paid consultation; completed allowed | Appointment ID substituted safely through membership predicate | Read-only; page bounded | Chat/clinical |
| `WS /p2p/live/{appointment_id}/{user_id}` | JWT in first frame; P owner or assigned D | Active paid consultation and time window | Path user must equal JWT user; sender is server-derived; membership rechecked on every saved message | 10s auth deadline, token-expiry close, 8KiB message cap | Chat/presence |
| `GET /video/token/{appointment_id}` | P owner or assigned D | Active paid consultation; both joined | Appointment membership selects fixed Agora UID; client UID absent | 30/hour + 10/minute | Video channel credential |
| Supabase `chat_room_{id}` presence | Authenticated Realtime member | Assigned, confirmed, paid appointment after tightening migration | `auth.uid()` maps through unique `supabase_auth_id`; metadata grants nothing | Realtime provider controls | Presence only |

## AI, Vault, lab, voice

| Method/path | Auth / roles | Ownership / entitlement | Client identifiers and server verification | Idempotency / rate | Sensitive |
|---|---|---|---|---|---|
| `POST /ai/consent` | Any | Self | No client user ID | Idempotent state | Consent |
| `GET /ai/consent/status` | Any | Self | No client user ID | Read-only | Consent |
| `POST /ai/consent/withdraw` | Any | Self | No client user ID | Idempotent state | Consent |
| `POST /chat/report` | Any | Self report | User derived from JWT; bounded message/reason | No key/rate decorator | Reported AI text |
| `POST /chat/image` | Any with AI consent | Self temporary namespace | Server creates `mediq_ai_temp/{user_id}/{uuid}`; actual image signature/size checked | 10/hour | Temporary clinical image |
| `DELETE /chat/image` | Any | Self temporary namespace | Public ID prefix must match current user | Safe provider delete | Temporary image |
| `POST /chat/analyze` | Any with AI consent | Self quotas; paid-only continuation/memory | Source summary and image public ID owner-bound; plan server-derived | One in-flight/user, request replay guard, 30/minute | Clinical AI context/provider cost |
| `POST /chat/analyze-document` | Any with AI consent | Self quotas; paid-only continuation/memory | Source owner/version checked; PDF bytes temporary and validated | One in-flight/user + 10/hour | Clinical PDF/provider cost |
| `POST /vault/ai-summary/save` | Paid Any | Self summary/source | Patient ID absent; source ID owner/version-bound; generated fields server-owned | User-bound request ID + payload fingerprint; 3/minute | Clinical summary |
| `GET /vault/history` | Any | Self records only | No client user ID | Read-only | Clinical |
| `POST /vault/export` | Any | Only requested IDs owned by caller are included | Record UUIDs filtered by current user | 5/minute | Clinical PDF |
| `DELETE /vault/ai-summary/{summary_id}` | Any | Self summary | ID and owner in same lookup | Safe 404 replay | Clinical |
| `DELETE /vault/record/{record_id}` | Any | Self AI/consultation record | Ownership checked before delete | Safe state transition | Clinical |
| `POST /lab/analyze` | Paid Any with AI consent | Self combined heavy-AI quota | User/plan from JWT/DB; actual image signature and 5MiB cap | One in-flight/user + 10/minute + failure guard | Clinical image/result/provider cost |
| `POST /voice/transcribe` | Any with AI consent | Self STT quota/reservation | User from JWT; audio type/size/duration validated | User-bound request digest, one in-flight, 10/hour, user/IP controls | Audio/transcript/provider cost |
| `POST /voice/speak` | Any | Self TTS quota | User/plan from JWT/DB; bounded text | Reserved/refunded quota; 20/hour + 5/minute | Text/audio/provider cost |

## Doctors, reviews, content

| Method/path | Auth / roles | Ownership / entitlement | Client identifiers and server verification | Idempotency / rate | Sensitive |
|---|---|---|---|---|---|
| `POST /doctors/me/reapply` | Rejected D | Self doctor row | Doctor from JWT; status checked | State guarded | Own verification metadata |
| `GET /doctors/` | Public | Verified doctors only | Pagination only | Read-only | Public schema excludes docs, bank and provider IDs |
| `GET /doctors/stats` | D | Self doctor/payout aggregates | Doctor from JWT | Read-only | Financial aggregate |
| `PUT /doctors/me` | D | Self doctor row | Allowlisted fields; server minimum price/duration | No key | Professional profile/pricing |
| `PUT /doctors/me/payout-settings` | Verified active D | Self doctor row | Bank details verified by Paystack and name match | 5/hour + 2/minute | Bank/provider cost |
| `GET /doctors/{doctor_id}` | Public | Verified doctor only | ID looked up under `is_verified` filter | Read-only | Public schema only |
| `POST /reviews/` | P | Own completed appointment | Appointment ownership/status checked; doctor derived | One review/appointment | Patient comment |
| `GET /content/tips` | Public | Published content | Pagination only | Read-only | No |
| `POST /content/admin/tips` | A | Admin content | Admin from JWT | No key | No |
| `PUT /content/admin/tips/{tip_id}` | A | Admin content | Tip exists; URL fields normalized | No key | No |
| `DELETE /content/admin/tips/{tip_id}` | A | Admin content | Tip exists | Safe replay after 404 | No |

## Emergency, family, notifications, support

| Method/path | Auth / roles | Ownership / entitlement | Client identifiers and server verification | Idempotency / rate | Sensitive |
|---|---|---|---|---|---|
| `POST /emergency/trigger` | Any | Own stored NOK; paid entitlement only for SMS | Name/NOK/user/plan/quota from DB; body owner fields forbidden | User-bound key + payload fingerprint, atomic cooldown/quota, 10/hour | Location/NOK/provider cost |
| `GET /emergency/local-services` | Any; no paid gate | Self request only | Validated coordinates; provider key server-side | Shared bounded cache + 30/hour | Approximate location/provider cost |
| `GET /family/invite-code` | Family primary only | Self primary; active family/capacity | No client family ID; random signed one-time nonce stored | New invite invalidates prior outstanding invite | Family relationship |
| `POST /family/join` | Any | Valid family primary and capacity | Signed expiring token + stored nonce; row lock; nonce consumed | One-time token | Family relationship/entitlement |
| `GET /notifications/` | Any | Self rows only | No client user ID | Read-only/paginated | Notification data |
| `GET /notifications/unread-count` | Any | Self | No client user ID | Read-only | Metadata |
| `PATCH /notifications/{notification_id}/read` | Any | ID + current user in same query | Notification ID substitution returns 404 | Boolean converges | Notification data |
| `POST /notifications/read-all` | Any | Self rows only | No client user ID | Convergent bulk update | Notification data |
| `POST /support/contact` | Any | Self submission | User/email/name/role from JWT/DB; body cannot forge identity | Globally unique request ID; user+payload checked; atomic send claim; 10/hour | Support body/email/provider cost |

## Payments and subscriptions

| Method/path | Auth / roles | Ownership / entitlement | Client identifiers and server verification | Idempotency / rate | Sensitive |
|---|---|---|---|---|---|
| `POST /payments/initialize` | Any | Self reference/account | Body email ignored; reference owner/type stored relationship, amount, currency and plan checked server-side | Provider reference + 20/hour + 5/minute | Financial/provider cost |
| `POST /payments/webhook` | Public provider callback | Paystack signature and authoritative event state | Raw body HMAC mandatory; reference/metadata/amount/plan/currency/environment revalidated | Durable event/payment keys; replay-safe | Financial |
| `GET /payments/verify/{reference}` | Any | Self reference/account | Ownership checked before provider call; successful response revalidated | Provider/reference state + 30/hour + 5/minute | Financial/provider cost |
| `POST /subscription/upgrade` | A only | Admin's own account; testing override | No client plan/user ID | No key + 10/hour | Entitlement |
| `POST /subscription/cancel-subscription` | Any | Self billing identifiers only | Subscription code/token loaded from current user | Provider state + 5/hour + 2/minute | Billing |
| `POST /subscription/restore` | Any | Self unexpired billing identifiers only | Subscription code/token loaded from current user | Provider state + 5/hour + 2/minute | Billing |

## Administration

Every route below uses `get_current_admin`; all caller identity and audit `admin_id` values are derived from the verified JWT/local role. Normal patients and doctors receive 403.

| Method/path | Ownership / validation | Idempotency / sensitive data |
|---|---|---|
| `GET /admin/stats` | Platform aggregates | Read-only; operational |
| `GET /admin/users` | Admin-wide user view | Read-only; private profiles |
| `PUT /admin/users/{user_id}/suspend` | Target exists; admin action | State mutation; private |
| `GET /admin/doctors/pending` | Pending verification rows | Read-only; verification documents |
| `PUT /admin/doctors/{doctor_id}/verify` | Target doctor/user exists | Approval state + audit/email |
| `POST /admin/doctors/{doctor_id}/reject` | Target exists; bounded reason | Rejection state + audit/email |
| `GET /admin/payouts` | Validated status filter | Read-only; financial |
| `PUT /admin/payouts/{payout_id}/approve` | State/hold/doctor prerequisites checked | State-convergent approval; financial/audited |
| `PUT /admin/payouts/{payout_id}/reject` | Awaiting state + bounded reason | State-convergent rejection; financial/audited |
| `GET /admin/refunds` | Validated status filter | Read-only; financial/private |
| `PUT /admin/refunds/{appointment_id}/approve` | Refund eligibility checked | State-convergent approval; financial/audited |
| `PUT /admin/refunds/{appointment_id}/reject` | Awaiting state + bounded reason | State-convergent rejection; financial/audited |
