# MDQ+ Sensitive Media Privacy Hardening

Date: 2026-09-14  
Status: Code complete; migration created but not executed; legacy asset reclassification remains an explicit deployment operation.

## 1. Existing Sensitive Media Architecture

### Pre-change inventory

| Media class | Upload/read path | Existing controls | Pre-change Cloudinary/storage model | DB/client exposure | Replacement/deletion |
|---|---|---|---|---|---|
| Doctor MDCN licence | `POST /api/v1/auth/doctor/register` | Verified Supabase identity, multipart form, 5 MiB per file, JPG/PNG/WebP/PDF signature validation | `resource_type=auto`, default `type=upload`, fixed `mdq_plus/doctor_licenses` folder | Permanent `secure_url` in `doctors.mdcn_license_url`; internal `DoctorResponse` returned it | Reapply could accept a caller-supplied URL and overwrite the field; no history |
| Doctor indemnity certificate | Same registration endpoint | Same | Default public `upload`, fixed `mdq_plus/indemnity_certs` folder | Permanent `secure_url` in `doctors.indemnity_cert_url` | Same overwrite/history weakness |
| Doctor public profile | `GET /api/v1/doctors` and `GET /api/v1/doctors/{id}` | Public, verified doctors only | No upload | `PublicDoctorResponse` already omitted document and payout fields | N/A |
| Admin doctor review | `GET /api/v1/admin/doctors/pending` | Admin role | Read the URL stored on the doctor row | `DoctorResponse` exposed permanent URLs; Flutter review UI incorrectly treated `license_number` as a possible URL | Approval/rejection changed status only |
| Lab scan image | `POST /api/v1/lab/analyze` | Auth, AI consent, paid-plan gate, quota/rate controls, image signatures, 5 MiB bound | Default public `upload`, `mediq_lab_scans` | Permanent `secure_url` in `lab_results.image_url`; analyze response returned only `record_id` | No lab-image deletion endpoint or formal retention lifecycle |
| AI chat image | `POST /api/v1/chat/image` then `/chat/analyze` | Auth, AI consent, user-scoped server-generated public ID, signatures, 5 MiB bound | Public `upload`, `mediq_ai_temp/{user_id}/{uuid}` | Flutter received URL plus public ID; backend rebuilt a public URL | Deleted after analysis; abandoned images swept after two hours |
| Profile images | `/api/v1/upload/` | Auth, images only, signature validation, 5 MiB | Public `upload`, fixed `mediq_profile_pics` | Public URL returned and later stored as profile image | Old assets are not currently destroyed on replacement |
| Generic app image upload | `/api/v1/media/upload` | Auth, images only, signature validation, 5 MiB, no client folder | Public `upload`, fixed `mdq_plus/general` | Public URL returned | No central replacement lifecycle |
| Health-tip artwork | Admin content APIs | Admin write; public read | Public URL/artwork | Public by product design | Existing content behavior |

Why sensitive media was public: Cloudinary's default `upload` delivery type makes assets publicly retrievable when their URL is known, and the application stored `secure_url` as the authoritative record. Random IDs reduced discoverability but did not provide authorization.

## 2. Final Storage/Delivery Model

### Doctor documents

- New licence and indemnity uploads use Cloudinary `type=authenticated`.
- The DB stores `public_id`, `resource_type`, `format`, and `delivery_type`; no new permanent URL is stored.
- Public, admin, and own-doctor schemas serialize no storage URL or public ID.
- `GET /api/v1/media/doctor-documents/{doctor_id}/{document_kind}/access` loads the doctor row, authorizes the caller, and signs only the server-owned identifier.
- Supported document kinds are the closed set `mdcn-license` and `indemnity-certificate`.

### Lab/clinical images

- Successful lab scans use authenticated delivery and store only stable Cloudinary identifiers.
- The analyze response still returns only the logical `record_id`, never a storage URL.
- `GET /api/v1/media/lab-images/{record_id}/access` is owner-patient-only and returns a short-lived URL.
- Doctor access is denied because `lab_results` has no appointment/consultation foreign key. Authorizing from a broad historical doctor-patient relationship would expose unrelated records and was not introduced.

### Transient AI media

- AI chat images now use authenticated delivery.
- The preview and backend analysis URLs expire after 15 minutes.
- Public IDs remain user-namespaced and server generated.
- Images are destroyed after analysis; both legacy `upload` and new `authenticated` abandoned images are included in the existing two-hour sweep.

### Public/non-sensitive media

- Profile images, health-tip artwork, branding, and general image uploads remain public by product design and are outside this hardening scope.

Cloudinary documents that `authenticated` protects originals and derived assets and requires authorized delivery, while the time-limited download API accepts an explicit expiry: [Cloudinary media access control](https://cloudinary.com/documentation/control_access_to_media).

## 3. Doctor Verification Flow Preservation

- Doctor registration is still bound to a verified Supabase identity.
- Uploading documents creates a `pending`, unverified, unavailable doctor application and an inactive operational user.
- Admin review is still mandatory.
- Only the existing admin verify operation sets `status=active`, `is_verified=true`, and activates the user.
- Doctor-only clinical capabilities remain behind the existing approved/active server guard.
- Approval, rejection, profile updates, reapplication, inactivity, and account deactivation do not delete verification documents.
- Reapplication no longer accepts caller-controlled document URLs. It preserves the existing evidence while allowing corrected licence metadata.
- The current product does not expose a pending-doctor self-view session: registration signs the doctor out and the general auth dependency rejects pending inactive users. Admin review remains available. Active/rejected owning doctors satisfy the record ownership rule if self-view is invoked.

## 4. Authorization Matrix

### Doctor documents

| Caller | Result |
|---|---|
| Owning doctor with an allowed authenticated session | Allowed for own row only |
| Authorized admin | Allowed |
| Patient | Hidden as 404 |
| Unrelated doctor | Hidden as 404 |
| Unauthenticated | 401 |
| Pending inactive doctor through current app flow | Blocked by existing pending-account gate; no pending self-view UI exists |

### Lab images

| Caller | Result |
|---|---|
| Owner patient | Allowed |
| Other patient | Hidden as 404 |
| Any doctor | Hidden as 404 until a specific lab-record/consultation authorization link exists |
| Admin | Hidden as 404; not part of the stated lab-image access policy |
| Unauthenticated | 401 |

## 5. Signed Access Design

- Doctor/lab access TTL: 300 seconds.
- Transient AI preview/analysis TTL: 900 seconds; storage cleanup remains two hours as a failure-recovery ceiling.
- Signing occurs server-side with the existing Cloudinary API secret through `private_download_url`.
- API secret and signing inputs are never returned.
- Callers submit only a logical doctor/record ID and a closed document-kind enum, never a Cloudinary public ID.
- Access responses set `Cache-Control: no-store, private`.
- The admin image viewer evicts its temporary `NetworkImage` after the dialog closes and offers a fresh-link action on expiry.
- PDF review obtains a new URL on every user action. OS/browser download caching after the URL is handed off is not fully controllable by Flutter.
- Provider failures use MDQ-owned messages and logs record only failure categories, not URLs, public IDs, filenames, or provider response text.

## 6. Retention / Replacement Behaviour

What remains:

- Committed doctor verification files remain after approval, rejection, inactivity, and metadata reapplication.
- Existing URL columns remain nullable for transition/audit recovery but are no longer serialized or trusted for delivery.
- Committed lab images follow the existing lab-record lifecycle; this task sets no legal retention period.

What is deleted:

- Sensitive uploads created during a doctor-registration or lab-record DB failure are best-effort deleted because no durable application record was committed.
- Transient AI images are deleted after analysis and by the stale-image sweep.

Deliberately unresolved:

- `doctors` has no document history table, `uploaded_at`, `verified_at`, `reviewed_by`, or durable decision-to-document-version linkage.
- A safe replacement feature therefore requires an additive versioned verification-document/audit model. This task does not create that larger schema or permit destructive replacement.
- `lab_results` has no formal record deletion endpoint or approved medical retention schedule. No deletion guess was added.

## 7. Existing Public Asset Transition

Changing new uploads does not protect historical `/upload/` assets. The code now refuses to turn legacy URL-only rows into access responses, but a copied historical URL can remain public until Cloudinary reclassification.

Required controlled transition:

1. Back up the doctor/lab rows and export a manifest of record ID, legacy URL, parsed public ID, resource type, and format. Do not include the manifest in ordinary logs or tickets.
2. Verify each parsed identifier against Cloudinary in staging; ambiguous or missing resources require manual review.
3. Change each confirmed sensitive asset from `upload` to `authenticated` using Cloudinary Rename with `to_type=authenticated` and CDN invalidation. Cloudinary supports delivery-type changes through `to_type`; cached copies can take time to invalidate: [Cloudinary access-control transition](https://cloudinary.com/documentation/control_access_to_media), [rename/invalidation behavior](https://cloudinary.com/documentation/rename_assets).
4. Populate the new nullable identifier/type/format columns only after the Cloudinary operation succeeds.
5. Verify the old `/upload/` URL is denied in incognito and the MDQ+ access endpoint succeeds.
6. Reconcile every manifest row; do not null or delete legacy URL columns yet.
7. Repeat with an approved, audited production change after staging acceptance.

No bulk media mutation or production rewrite was executed.

## 8. Migration Status

Created, not executed:

- `backend/migrations/add_private_sensitive_media_identifiers.sql`

It adds nullable identifier metadata for two doctor documents and the lab image plus authenticated-delivery check constraints. It does not parse URLs, reclassify Cloudinary resources, delete files, or remove legacy columns.

Deployment order is mandatory:

1. Back up staging DB.
2. Apply `add_private_sensitive_media_identifiers.sql`.
3. Deploy backend.
4. Deploy Flutter/admin client.
5. Exercise new authenticated uploads.
6. Run the separately reviewed legacy reclassification/backfill plan.

Deploying the ORM code before the columns exist can break doctor/lab queries.

## 9. Cloudinary Deployment Requirements

- Keep `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, and `CLOUDINARY_API_SECRET` server-side in staging/production.
- Do not add the API secret to Flutter, Supabase public settings, logs, Sentry context, support mail, or notification payloads.
- Confirm staging permits authenticated uploads and signed `private_download_url` delivery for both image and PDF formats.
- On Cloudinary Free environments, PDF delivery is blocked by default; enable **Allow delivery of PDF and ZIP files** only if PDF doctor documents are accepted, then verify that authentication is still required: [Cloudinary PDF security setting](https://cloudinary.com/documentation/pdf_optimization).
- Keep backend host time synchronized because expiry validation is time based.
- No Cloudinary Auth Token key or premium token-based access feature is required by this implementation; it uses the signed, expiring download API.
- No Cloudinary dashboard setting was changed automatically.

## 10. Tests

Commands and results:

```text
cd backend
$env:PYTHONDONTWRITEBYTECODE='1'
venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_sensitive_media_privacy.py tests/test_security_sweep.py
32 passed

venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
270 passed, 24 subtests passed

cd frontend
flutter test test/sensitive_media_access_test.dart
2 passed

flutter test test/sensitive_media_access_test.dart test/ai_chat_controller_test.dart test/ai_error_surface_test.dart test/api_error_mapper_test.dart test/auth_interceptor_test.dart test/auth_router_policy_test.dart test/vault_cache_isolation_test.dart test/consultation_session_controller_test.dart
63 passed

git diff --check
passed

flutter analyze --no-pub
completed with 166 existing project warning/info findings and no compile errors;
exit 1 because this repository treats analyzer findings as a non-zero result

dart analyze lib/src/core/media
No issues found

dart analyze test/sensitive_media_access_test.dart
No issues found
```

Coverage includes unauthenticated denial, owner/admin access, cross-user and unrelated-doctor denial, public-schema omission, short expiry, no arbitrary public-ID signing, legacy URL blocking, authenticated upload parameters, spoofed/oversized/path-traversal rejection, safe provider failure output/logs, transient authentication/cleanup, and Flutter logical-record access calls.

## 11. Manual Staging Acceptance

### Doctor onboarding

1. Apply the new DB migration to staging; do not deploy the new backend first.
2. Register a new doctor with JPG/PNG verification documents.
3. Repeat with a PDF document if PDF support is enabled.
4. Confirm the doctor row has authenticated identifier metadata and null new legacy URL fields.
5. Confirm the application remains `pending`, `is_verified=false`, `is_available=false`, and the operational user remains inactive.
6. Confirm the pending doctor cannot open operational doctor dashboard/consultation APIs.
7. Sign in as admin and open Verifications.
8. Confirm licence and indemnity availability controls render without raw URLs or public IDs.
9. Open each document and confirm the five-minute access response works.
10. Copy the returned URL, wait more than five minutes, and confirm it fails.
11. Use “Request a fresh link”/reopen and confirm a new URL works without logging the admin out.
12. Approve the doctor and confirm operational doctor access becomes available.
13. Confirm the admin can still access both documents after approval by calling the same record-bound endpoints.

### Cross-user isolation

14. As a patient, call both doctor-document access paths and confirm 404.
15. As an unrelated doctor, call both paths and confirm 404.
16. Call without a bearer token and confirm 401.
17. Attempt to add a `public_id` query/body value and confirm it is ignored/rejected; there is no arbitrary signing contract.

### Lab

18. As Patient A on an eligible plan with AI consent, complete a successful lab scan.
19. Confirm the analyze response contains `record_id` but no URL/public ID.
20. Request `/api/v1/media/lab-images/{record_id}/access` and view the image.
21. Copy the URL and confirm it fails after five minutes; request a fresh URL and confirm recovery.
22. As Patient B, request Patient A's record and confirm 404.
23. As a doctor, request Patient A's record and confirm 404 because no lab-record consultation link exists.

### Public exposure and cleanup

24. Confirm public doctor list/detail JSON contains no licence/document URL, public ID, bank field, or payout identifier.
25. Upload a transient AI image and confirm its raw `/authenticated/` storage URL is denied without signed access.
26. Complete/cancel analysis and verify the asset is deleted; verify the two-hour sweep handles an abandoned authenticated fixture.
27. Review Render/Sentry/app logs and confirm no signed URLs, public IDs, document filenames, or provider error text.
28. For a staged legacy fixture, perform the reviewed `to_type=authenticated` transition with invalidation and verify the old `/upload/` URL is denied.

## 12. Remaining Risks / Compliance Decisions

1. Historical public assets remain the primary deployment risk until every sensitive URL-only row is reclassified and reconciled. Code alone cannot revoke a copied old URL.
2. Doctor document history needs an architecture decision before document replacement is reintroduced. A versioned evidence model should bind each review decision to immutable document versions and reviewer/timestamps.
3. Formal doctor-document and lab-image retention/deletion periods require legal/compliance approval; none were invented here.
4. Authorized doctor access to lab images needs an explicit lab-record-to-consultation (or other clinical authorization) relationship. It is denied until that model exists.
5. Short-lived URLs are bearer links during their five-minute lifetime. They substantially reduce exposure but cannot prevent an authorized viewer from copying content.
6. External PDF viewers and operating systems may retain downloaded data outside Flutter's in-memory cache controls.
7. Cloudinary data-processing, regional storage, employee-access, and IP-log settings remain organizational compliance decisions.

Stop point: architecture review is required for legacy reclassification execution, document-version history, doctor-to-lab authorization, and formal retention policy.

## 13. Files Changed

Backend:

- `backend/app/services/media_service.py`
- `backend/app/api/v1/auth.py`
- `backend/app/api/v1/doctors.py`
- `backend/app/api/v1/media.py`
- `backend/app/api/v1/lab.py`
- `backend/app/api/v1/chat.py`
- `backend/app/models/doctor.py`
- `backend/app/models/lab_result.py`
- `backend/app/schemas/doctor.py`
- `backend/app/schemas/lab.py`
- `backend/migrations/add_private_sensitive_media_identifiers.sql`
- `backend/tests/test_sensitive_media_privacy.py`

Flutter:

- `frontend/lib/src/core/media/sensitive_media_access.dart`
- `frontend/lib/src/features/admin/presentation/admin_dashboard.dart`
- `frontend/lib/src/features/lab/data/lab_repository.dart`
- `frontend/lib/src/features/auth/data/auth_repository.dart`
- `frontend/lib/src/features/chat/data/image_upload_service.dart`
- `frontend/lib/src/features/chat/presentation/ai_chat_controller.dart`
- `frontend/lib/src/features/chat/presentation/ai_chat_screen.dart`
- `frontend/test/sensitive_media_access_test.dart`

Report:

- `docs/reports/sensitive_media_privacy_hardening_2026-09-14.md`
