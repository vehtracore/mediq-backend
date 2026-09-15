# Doctor verification legacy transition

Apply `backend/migrations/add_private_sensitive_media_identifiers.sql` first,
complete its private/authenticated Cloudinary identifier classification, and
then apply `backend/migrations/add_doctor_verification_history.sql`.

The history migration intentionally creates no submissions for existing
doctors. Existing approved doctors continue to operate from `doctors.status`,
`doctors.is_verified`, and the associated active user state while
`current_verification_submission_id` is null.

For a controlled legacy import, compliance must first confirm that the current
private identifiers genuinely belong to the doctor and represent the retained
credential package. An authorized, separately reviewed backfill may then create
one `legacy_import` submission with `historical_unknown` status and document
rows containing digests calculated from the exact retrieved bytes. Reviewer,
review timestamp, submission timestamp, rejection reason, and supersession must
remain null/unknown unless supported by an authoritative source. A legacy
import is historical context, not a newly inferred approval decision.

Do not copy public legacy URLs into the evidence tables. Records still awaiting
private-media reclassification remain outside versioned history until that
work is complete. No legacy document is deleted by this transition.
