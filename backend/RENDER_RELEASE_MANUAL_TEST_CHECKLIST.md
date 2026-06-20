# MDQ+ Render Release and Manual Test Checklist

Last updated: 2026-06-20

This document records the targeted work completed during the appointment,
consultation, payment, subscription/AI-cost-control, and AI-consent audits. It
is a release verification guide, not a claim of complete security, regulatory,
clinical, or payment compliance.

## 1. Release preparation

- [ ] Review the final Git diff and exclude `__pycache__` and `.pyc` files.
- [ ] Back up the production PostgreSQL database.
- [ ] Deploy to a Render staging service first, using Paystack test keys.
- [ ] Confirm the backend starts without a schema-patch exception.
- [ ] Confirm `/docs` loads only if API documentation is intentionally enabled.
- [ ] Confirm the health endpoint and authenticated `/auth/me` request succeed.
- [ ] Confirm server errors are written to Render/Sentry logs and users receive
      short messages such as "Service unavailable. Please try again."

## 2. Database migrations

Apply or verify these migrations before production traffic:

- [ ] `add_ai_consent_fields.sql`
- [ ] `add_ai_summary_review_metadata.sql`
- [ ] `add_consultation_attendance.sql`
- [ ] `add_doctor_consultation_pricing.sql`
- [ ] `enforce_30_minute_consultations.sql`
- [ ] `add_general_queue_payout_ledger.sql`
- [ ] `add_consultation_refund_workflow.sql`

After migration:

- [ ] New appointments have a durable appointment type.
- [ ] Doctor consultation duration is 30 minutes.
- [ ] Minimum consultation fee is NGN 4,000.
- [ ] New general-queue payouts default to `awaiting_admin`.
- [ ] Legacy unapproved payout/refund rows are returned to admin review.
- [ ] AI consent and AI summary review metadata columns exist.

## 3. Render environment settings

Set the production values required by the enabled features:

- [ ] `DATABASE_URL`
- [ ] `SECRET_KEY`, `ALGORITHM`
- [ ] `SUPABASE_URL`, `SUPABASE_JWT_AUDIENCE`
- [ ] `PAYSTACK_SECRET_KEY`
- [ ] `GEMINI_API_KEY`
- [ ] `GEMINI_STANDARD_MODEL`, `GEMINI_HEAVY_MODEL` if overriding defaults
- [ ] `OPENAI_API_KEY`, `YARNGPT_API_KEY`, `YARNGPT_TTS_URL`
- [ ] `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`,
      `CLOUDINARY_API_SECRET`
- [ ] `AGORA_APP_ID`, `AGORA_APP_CERTIFICATE`
- [ ] `TERMII_API_KEY`, `TERMII_SENDER_ID`
- [ ] `RESEND_API_KEY`, `RESEND_FROM_EMAIL`, `EMAIL_FROM`
- [ ] `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
- [ ] `FIREBASE_CREDENTIALS`
- [ ] Redis URL used by the deployment (`UPSTASH_REDIS_REST_URL` currently)
- [ ] `SENTRY_DSN`, `ADMIN_EMAIL`, and `Maps_API_KEY` where applicable

Never put secret values in Flutter, source control, logs, or screenshots.

Flutter build note:

- [ ] `frontend/.env` is intentionally ignored and currently contains only
      `SUPABASE_URL` and `SUPABASE_ANON_KEY`. Any remote Flutter build pipeline
      must recreate this file before `flutter build` because it is declared as
      an asset in `pubspec.yaml`.
- [ ] Restrict Firebase/Google API keys to the expected Android package and
      signing SHA fingerprints, iOS bundle ID, and approved web domains.

## 4. Paystack dashboard configuration

- [ ] Use test mode for all tests in this document.
- [ ] Set the webhook URL to:
      `https://<render-host>/api/v1/payments/webhook`
- [ ] Confirm the webhook secret is the same Paystack secret key used by Render.
- [ ] Enable Transfers for the business and fund the Paystack test balance.
- [ ] Open Paystack Dashboard > Preferences.
- [ ] For automatic transfer after MDQ+ admin approval, uncheck
      **Confirm transfers before sending**.

Transfer OTP is a Paystack business-account control. When confirmation is
enabled, Paystack sends a one-time code to the business phone and an initiated
transfer requires a separate finalize call. It is not an OTP created inside
MDQ+. MDQ+ already requires its own authenticated admin approval before the
transfer worker can initiate a payout.

## 5. Authentication and user-facing errors

- [ ] Wrong email/password displays "Invalid email or password", not an
      exception or stack trace.
- [ ] Expired/invalid authentication returns a brief sign-in message.
- [ ] Banned users cannot access protected endpoints.
- [ ] Patient endpoints reject doctor/admin tokens where role-specific.
- [ ] Doctor endpoints reject patient/admin tokens where role-specific.
- [ ] API/network/AI/payment failures never expose implementation details,
      secret keys, SQL, provider payloads, or stack traces in the UI.

## 6. Appointment authorization: all three flows

### General queue

- [ ] Patient can create a `general_queue` appointment.
- [ ] It starts paid/unpaid exactly as intended by checkout state.
- [ ] Queue shows only minimum triage information before claim.
- [ ] Unapproved doctor cannot view or claim the queue.
- [ ] Unavailable doctor cannot claim.
- [ ] Claim requires paid, pending, unassigned, no-slot general appointment.
- [ ] Two doctors racing to claim: one succeeds and the other gets conflict.
- [ ] After claim, only patient and assigned doctor can access/modify it.
- [ ] Another doctor cannot accept, decline, cancel, complete, prescribe,
      refer, join chat, or join video.

### Specialist scheduled session

- [ ] Unauthenticated caller cannot create a doctor slot.
- [ ] Doctor cannot create a slot for another doctor.
- [ ] Approved active doctor can create their own slot.
- [ ] Patient books an available slot and doctor is derived from the slot.
- [ ] Two patients cannot book the same slot.
- [ ] Another doctor cannot claim or modify the appointment.
- [ ] Another patient cannot pay, cancel, acknowledge, chat, or join video.
- [ ] Unpaid slot-holding behaviour matches the documented expiry policy.

### VIP doctor request

- [ ] Patient requests a specific doctor and type is `vip_request`.
- [ ] Only the requested approved doctor can propose date/time.
- [ ] Another doctor cannot propose, accept, cancel, or complete it.
- [ ] Only the requesting patient can accept and pay.
- [ ] Confirmed session belongs only to that doctor and patient.

### Shared patient/doctor actions

- [ ] Patient A cannot cancel or acknowledge Patient B's appointment.
- [ ] Patient A cannot directly mark Patient B's appointment paid.
- [ ] Doctor A cannot accept/decline/cancel/complete Doctor B's appointment.
- [ ] Prescribe/referral require the assigned approved doctor.
- [ ] Invalid status transitions return conflict and do not mutate data.
- [ ] The manual `PUT /appointments/{id}/pay` path is unavailable to users.

## 7. Consultation pricing and payment verification

- [ ] Every consultation duration is 30 minutes.
- [ ] Doctor cannot save a consultation fee below NGN 4,000.
- [ ] Fee is edited only from Edit Profile.
- [ ] Public profile does not display a hard-coded platform split.
- [ ] Payment initialize requires the authenticated appointment owner.
- [ ] Payment amount, appointment ID, user ID, type, reference, and expected
      fee are validated server-side.
- [ ] Forged amount/reference/type is rejected.
- [ ] Payment verification cannot mark another patient's appointment paid.
- [ ] Paystack `charge.success` updates consultation state only once.
- [ ] Subscription events cannot accidentally activate from consultation
      payments.

Expected NGN 4,000 consultation split:

- Platform gross commission: NGN 1,480 (37%), before Paystack/platform costs.
- Doctor payout: NGN 2,520 (63%).

Specialist/VIP payments use the assigned doctor's Paystack subaccount at
checkout. General queue cannot split at checkout because no doctor is assigned
until claim, so its doctor share uses the post-consultation payout ledger.

## 8. Attendance, timing, video, chat grace, and no-shows

- [ ] Scheduled/VIP room opens 10 minutes before scheduled time.
- [ ] General queue room is available after claim/confirmation.
- [ ] Timer does not start when only one participant joins.
- [ ] Timer starts once, when the second authenticated participant joins.
- [ ] Rejoining does not reset `consultation_started_at`.
- [ ] Both users see a warning at 25 consultation minutes.
- [ ] Video access ends at 30 consultation minutes.
- [ ] Consultation messaging remains available for the 10-minute grace period.
- [ ] Appointment auto-completes after the message grace period.
- [ ] Scheduled/VIP attendance grace is 15 minutes.
- [ ] General queue attendance grace is 5 minutes.
- [ ] Doctor present, patient absent becomes `patient_no_show`.
- [ ] Patient present, doctor absent becomes `doctor_no_show`.
- [ ] Neither present becomes `both_no_show`.
- [ ] Patient no-show creates the eligible doctor payout obligation.
- [ ] Doctor/both no-show creates a patient refund awaiting admin review.
- [ ] Doctor/both no-show never creates a doctor payout.

## 9. Doctor payout onboarding and admin approval

- [ ] Doctor payout setup resolves the Nigerian account with Paystack.
- [ ] Account name mismatch is rejected.
- [ ] Updating bank details clears the old transfer-recipient code.
- [ ] Missing bank details prevent payout approval.
- [ ] Completed/patient-no-show general session creates one payout row.
- [ ] New payout status is `awaiting_admin`.
- [ ] Non-admin cannot list, approve, or reject payouts.
- [ ] Admin sees doctor, patient, appointment outcome, amount, attendance,
      payment status, bank readiness, and current payout status.
- [ ] Admin can reject only an uninitiated payout and must provide a reason.
- [ ] Admin can approve only a matching paid eligible appointment.
- [ ] Amount or doctor mismatch prevents approval.
- [ ] Only `approved` rows reach the payout worker.
- [ ] Approved payout initiates exactly one Paystack transfer.
- [ ] `transfer.success` credits doctor earnings exactly once.
- [ ] Duplicate success webhook does not double-credit earnings.
- [ ] Failed, blocked, processing, paid, rejected, reversed, and OTP-required
      payouts appear under their admin status filters.
- [ ] Transfer reversal removes the prior earnings credit once.
- [ ] Admin ID/timestamp and audit log exist for approval/rejection.

## 10. Patient no-show refund workflow

- [ ] Only `doctor_no_show` and `both_no_show` paid appointments are eligible.
- [ ] Refund amount equals the original paid appointment amount.
- [ ] Missing Paystack transaction reference prevents approval.
- [ ] New refund status is `awaiting_admin`.
- [ ] Non-admin cannot list, approve, or reject refunds.
- [ ] Admin can review attendance before approving/rejecting.
- [ ] Rejection requires a reason and remains auditable.
- [ ] Only `approved` refunds reach the refund worker.
- [ ] Paystack receives the original transaction reference and exact amount.
- [ ] `refund.pending`, `processing`, `needs-attention`, `failed`, and
      `processed` webhooks update the appointment.
- [ ] Processed refund changes payment status to `refunded`.
- [ ] A network timeout becomes `verification_required`; confirm the result in
      Paystack before any operational retry to prevent a duplicate refund.
- [ ] `needs_attention` is visible to admin for customer-bank follow-up.
- [ ] Refund history/status filters work in the admin console.

## 11. Subscription, family, and AI fair-use controls

- [ ] Premium checkout charges the configured NGN 3,500 monthly plan.
- [ ] Subscription activation happens only after verified Paystack success.
- [ ] Cancellation disables renewal but keeps access until expiry.
- [ ] Restore/re-enable works before expiry where Paystack permits.
- [ ] Family host can add only the allowed number of dependants.
- [ ] Family dependant inherits the correct family access.
- [ ] Cancelling/expiring the host plan removes dependant paid access correctly.
- [ ] Free AI allowance: 12 text messages and 2 image messages per month.
- [ ] Premium: 300 standard messages per month soft threshold.
- [ ] Family: 250 standard messages per member per month soft threshold.
- [ ] After paid soft threshold, only 5 priority messages per rolling 24 hours.
- [ ] Anti-spam allows 15 messages in 15 minutes, then pauses further requests
      for 15 minutes.
- [ ] Paid heavy AI allowance combines chat photos and lab scans: 10/month.
- [ ] Text AI remains available after the heavy-feature quota is reached.
- [ ] Failed provider requests do not consume successful-use quota.
- [ ] Counters reset at the intended calendar-month/rolling-window boundaries.
- [ ] Concurrent requests cannot bypass quota enforcement when Redis is active.

## 12. AI consent, prompt boundaries, storage, and images

- [ ] First AI entry displays the consent disclosure once.
- [ ] Disclosure mentions health text, chronic conditions, symptoms, and images
      may be processed by a third-party AI provider.
- [ ] Disclosure says AI is not diagnosis, prescription, or emergency care.
- [ ] Privacy Policy and Terms links open.
- [ ] Cancel does not grant consent or send health data to Gemini.
- [ ] Continue stores consent timestamp and version.
- [ ] Active consent is not recreated on every session.
- [ ] Withdrawn consent blocks chat, image upload, and lab analysis with 403.
- [ ] Granting consent again restores access.
- [ ] Backend enforces consent before any Gemini call.
- [ ] AI prompt does not claim to be a certified technician/clinician.
- [ ] Output remains useful informational support, avoids definitive diagnosis
      and prescribing, recommends licensed care, and gives Nigerian emergency
      guidance (112/199 or nearest hospital) where appropriate.
- [ ] Standard text and heavy/image tasks use the intended configured models.
- [ ] Raw AI chats are not stored in the MDQ+ database.
- [ ] Conversation continuity uses bounded recent context and client-held
      summary memory, not an automatically saved raw transcript.
- [ ] Exit and Delete clears local messages and deletes the temporary image.
- [ ] Image is deleted after analysis even when Gemini fails.
- [ ] Abandoned temporary AI images are removed after the configured two-hour
      cleanup window.
- [ ] User cannot delete or use another user's temporary image public ID.
- [ ] Exit and Save sends only the generated summary to the vault.

## 13. AI Health Vault summary

- [ ] Title remains "AI Summary".
- [ ] Document body states it is AI-generated and not reviewed by a doctor.
- [ ] Stored metadata is `source=ai_generated`,
      `doctor_review_status=not_reviewed`, no reviewer, no review timestamp.
- [ ] Raw chat messages and uploaded chat images are not saved with the summary.
- [ ] Patient can export the summary and the disclosure appears in the export.
- [ ] Patient can delete their own summary.
- [ ] Patient cannot read/delete another patient's summary by changing the ID.
- [ ] Saving is explicit; exiting without save creates no vault summary.

## 14. Logs, privacy, and operational checks

- [ ] Production logs do not contain raw AI prompts, health histories,
      prescriptions, full payment payloads, bank account numbers, API keys,
      tokens, or uploaded image contents.
- [ ] Queue responses do not expose full clinical history before doctor claim.
- [ ] Paystack webhook signature mismatch is rejected.
- [ ] Structurally failed webhooks enter the failed-webhook queue for review.
- [ ] Duplicate webhooks remain idempotent.
- [ ] Removed routes return 404:
      `/api/v1/admin/fix-schema` and `/api/v1/admin/delete-test-users`.
- [ ] Scheduler runs once per intended deployment topology; if Render runs
      multiple web workers, confirm conditional database claims prevent
      duplicate payout/refund initiation.
- [ ] Sentry/Render alerts exist for failed payouts, refund verification
      required, failed webhooks, and scheduler exceptions.

## 15. Automated checks before commit

Run from `backend`:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
python -m compileall -f app tests
```

Run from `frontend`:

```powershell
dart format lib
flutter analyze --no-pub
```

Run from repository root:

```powershell
git diff --check
git status --short
```

Do not commit generated `__pycache__`, `.pyc`, secrets, local databases,
uploaded medical files, or provider credentials.

## 16. Production go/no-go

Go live only when:

- [ ] All migrations succeeded and a rollback/backup exists.
- [ ] Paystack test checkout, split, payout, transfer webhook, refund, and
      refund webhook tests passed.
- [ ] Appointment authorization tests passed using separate patient/doctor
      accounts.
- [ ] AI consent and temporary-image deletion tests passed.
- [ ] No critical error is visible to end users.
- [ ] Failed-webhook, payout, refund, Sentry, and Render logs were reviewed.
- [ ] A named operator owns daily payout/refund exception review.
