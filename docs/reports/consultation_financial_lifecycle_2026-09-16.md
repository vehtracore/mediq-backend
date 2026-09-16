# Consultation financial lifecycle audit

This describes the repository implementation reviewed on 2026-09-16. It does
not assert the state of live Paystack transactions or the Supabase dashboard.

1. **Payment.** `payments.py::_apply_db_update` handles
   `gp_consult`, `specialist_consult`, and `vip_request`. It sets
   `Appointment.payment_status = "paid"`. A direct or VIP booking with an
   assigned doctor becomes `confirmed`; a general queue booking remains
   `pending`. The appointment stores `amount`, `commission`, `payout`, and
   `paystack_reference` (`models/appointment.py`). The payment handler queues
   a confirmation email to the patient, and `_emit_payment_notification`
   creates payment and, where applicable, doctor confirmation notifications.
   This code does not transfer the doctor's share at payment time.
2. **Completion and payout obligation.** Both the doctor completion endpoint
   (`appointments.py::complete_appointment`) and automatic completion use
   `consultation_completion.py::complete_consultation`. It marks the appointment
   `completed`, updates the vault record, and calls
   `ensure_consultation_payout`. The unique
   `ConsultationPayout.appointment_id` and unique transfer `reference` create
   one ledger row per consultation with status `awaiting_admin`. The completed
   patient notification is sent after commit. No payout approval is implicit
   in completion.
3. **Hold.** `consultation_payout_hold_until` calculates 24 hours after the
   consultation's 30-minute session plus 10-minute message grace, measured
   from `consultation_started_at`. For `patient_no_show`, the hold starts at
   `no_show_marked_at`. Payout approval and transfer eligibility require this
   hold to elapse. The completed-consultation complaint endpoint accepts a
   request only while the same hold has not expired; the client also filters
   eligible appointments with `Appointment.canPatientReportIssue`.
4. **Complaint and refund review.** `POST /appointments/{id}/complaint`
   verifies patient ownership, completed and paid status, the hold window,
   a nonempty reason, and absence of an existing refund status. It sets
   `refund_status = "awaiting_admin"`, `refund_amount = amount`, and
   `refund_last_error = "Patient complaint: ..."`. It does not initiate a
   refund. After committing the refund review, the follow-up implementation
   creates a durable support email record and sends a reconciliation copy to
   `mdqplus.info@gmail.com`; a delivery failure leaves the refund review
   intact. No complaint-specific product notification is emitted.
   The same `awaiting_admin` state is set for eligible no-show or queue
   failures by the appointment scheduler; an external Paystack dispute can
   also enter review through `payments.py`.
5. **Payout blocking.** `eligible_consultation_payout_amount` requires a paid,
   eligible consultation with a doctor, a positive split amount, the elapsed
   hold, and no blocking `refund_status`. The blocking set includes
   `awaiting_admin`, `approved`, `pending`, `processing`, `needs_attention`,
   `verification_required`, and `processed`. Admin approval rechecks these
   conditions, and the transfer worker rechecks them before claiming an
   approved payout. A rejected refund is not blocking.
6. **Admin review.** `GET /admin/payouts` defaults to `awaiting_admin` and
   includes appointment/payment/refund status, hold time, bank readiness,
   joins, amount, and audit fields. `PUT /admin/payouts/{id}/approve` validates
   the hold, eligibility, matching doctor/amount, and bank details, then sets
   status `approved` with admin ID/time and an audit log. The admin can reject
   only an uninitiated `awaiting_admin` payout. `GET /admin/refunds` defaults
   to `awaiting_admin` and exposes appointment/refund/payment references,
   amount, attendance, approval fields, and last error. Refund approval
   validates eligibility and sets `approved` with admin ID/time and an audit
   log; rejection is limited to `awaiting_admin`.
7. **External action.** `process_approved_consultation_payouts` claims only
   `approved` payouts, marks `processing`, and initiates a Paystack transfer
   using the unique ledger reference. `transfer.success` marks it `paid`,
   records `paid_at`, credits doctor earnings once, and emits `PAYOUT_SENT`.
   `process_approved_consultation_refunds` claims only `approved` refunds,
   marks `processing`, and calls Paystack refund using the original transaction
   reference. A processed refund sets `payment_status = "refunded"` and
   `refund_processed_at`; the refund webhook maintains later status updates.
   The refund path does not emit a refund decision email or notification.
8. **Double action controls.** Completed-consultation flows separate the
   complaint window from payout approval and block payout while a refund is
   under review. The follow-up implementation makes both admin approvals and
   complaint submission lock the appointment row first, then re-check the
   opposite payout/refund state before committing. A conflicting approval
   returns HTTP 409. The refund worker also checks the payout state before
   calling Paystack; the payout worker already checks the refund state.
   Unique references and worker status claims retain each pipeline's
   idempotency. The mutual exclusion relies on transactional row locking in
   PostgreSQL rather than a new database constraint.
9. **Demonstrated defect fixed.** Before this change,
   `eligible_consultation_refund_amount` recognized a completed consultation
   only while its refund was `awaiting_admin`. The refund worker first changes
   an approved refund to `processing`, so it then failed that eligibility
   check. The check now also accepts `approved` and `processing` for the
   already-entered completed-consultation dispute; admin approval remains
   restricted to `awaiting_admin`.

Primary code: `backend/app/api/v1/payments.py`,
`backend/app/api/v1/appointments.py`, `backend/app/api/v1/admin.py`,
`backend/app/services/consultation_completion.py`,
`backend/app/services/consultation_payout_service.py`,
`backend/app/services/consultation_refund_service.py`,
`backend/app/models/appointment.py`, and
`backend/app/models/consultation_payout.py`.
