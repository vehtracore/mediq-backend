# Appointment Authorization Manual Verification

This checklist verifies the targeted appointment authorization changes.
It does not establish full security or regulatory compliance.

## Test identities

Prepare separate authenticated accounts:

- Patient A
- Patient B
- Active Doctor A
- Active Doctor B
- Inactive Doctor
- Admin, if the deployment supports an admin role

Prepare these appointments:

- Patient A general queue appointment: `general_queue`, `pending`, `paid`,
  unassigned, no slot
- Patient B general queue appointment: `general_queue`, `pending`, `paid`,
  unassigned, no slot
- Patient B specialist appointment assigned to Doctor B
- Patient B VIP request assigned to Doctor B
- Completed appointment owned by Patient B
- Cancelled general queue appointment

Record appointment and slot IDs before starting.

## Slot creation

### Unauthenticated caller

Call `POST /api/v1/appointments/slots` without a bearer token.

Expected:

- Request is rejected with `401`.
- No slot is created.

### Doctor creates another doctor's slot

Authenticate as Doctor A and submit Doctor B's `doctor_id`.

Expected:

- Request is rejected with `403`.
- No slot is created for Doctor B.

### Doctor creates own slot

Authenticate as Doctor A and submit Doctor A's `doctor_id` with a future time.

Expected:

- Request succeeds with `201`.
- Returned slot belongs to Doctor A.

### Inactive doctor

Authenticate as an inactive doctor account and attempt to create a slot.

Expected:

- Authentication or endpoint authorization rejects the request.
- No slot is created.

## Patient actions

### Cross-patient cancellation

Authenticate as Patient A and call:

`PUT /api/v1/appointments/{patient_b_appointment_id}/cancel`

Expected:

- Request is rejected with `403`.
- Patient B's appointment and slot remain unchanged.

### Owner cancellation

Authenticate as the owning patient and cancel an appointment in `pending`,
`awaiting_payment`, or `confirmed`.

Expected:

- Request succeeds.
- Status becomes `cancelled`.
- Only the appointment's own linked slot is released.

Attempt cancellation for a `completed` or already `cancelled` appointment.

Expected:

- Request is rejected with `409`.

For a scheduled specialist or timed VIP appointment, attempt cancellation:

- One second before the scheduled start
- At the scheduled start
- After the scheduled start

Expected:

- Cancellation before the scheduled start is allowed while the status remains
  otherwise cancellable.
- Cancellation at or after the scheduled start returns `409`.
- Appointment status and slot booking remain unchanged after rejection.

For a general-queue appointment, attempt cancellation before and after a
doctor claims it.

Expected:

- A pending, unclaimed queue appointment can be cancelled.
- A claimed/confirmed queue appointment returns `409`.
- The assigned doctor and appointment status remain unchanged after rejection.

### Cross-patient acknowledgement

Authenticate as Patient A and acknowledge Patient B's appointment.

Expected:

- Request is rejected with `403`.
- `is_acknowledged` remains unchanged.

### Direct payment mutation

Authenticate as either patient and call:

`PUT /api/v1/appointments/{appointment_id}/pay`

Expected:

- Request returns `410 Gone`.
- `payment_status` remains unchanged.

## Doctor assignment

### Cross-doctor accept

Authenticate as Doctor A and accept Doctor B's specialist appointment.

Expected:

- Request is rejected with `403`.
- Appointment status remains unchanged.

### Cross-doctor decline

Authenticate as Doctor A and decline Doctor B's appointment.

Expected:

- Request is rejected with `403`.
- Appointment and linked slot remain unchanged.

### Cross-doctor cancellation

Authenticate as Doctor A and cancel Doctor B's appointment.

Expected:

- Request is rejected with `403`.
- Appointment and linked slot remain unchanged.

### Cross-doctor completion

Authenticate as Doctor A and complete Doctor B's appointment.

Expected:

- Request is rejected with `403`.
- No consultation vault record is created.

### Invalid transitions

Using the assigned doctor, verify:

- Only a `pending`, paid appointment can be accepted.
- Only a `pending` appointment can be declined.
- Only `awaiting_payment` or `confirmed` can be doctor-cancelled.
- Only a `confirmed`, paid appointment can be completed.

Expected:

- Invalid transitions return `409`.
- No appointment, slot, or consultation record is mutated.

### Prescription and referral assignment

Authenticate as Doctor A and prescribe or refer against Doctor B's appointment.

Expected:

- Request is rejected with `403`.
- No prescription, referral, PDF, email, or vault update is produced.

## VIP request

### Wrong doctor proposes

Authenticate as Doctor A and propose a time for Patient B's VIP request assigned
to Doctor B.

Expected:

- Request is rejected with `403`.
- Start time and status remain unchanged.

### Correct doctor proposes

Authenticate as Doctor B and propose a future time within 30 days for a
`vip_request` in `pending` and `unpaid`.

Expected:

- Request succeeds.
- Start time is stored.
- Status becomes `awaiting_payment`.

Verify that past times, times beyond 30 days, non-VIP appointments, paid
appointments, and non-pending requests are rejected.

## General queue

### Queue visibility

Authenticate as an active doctor and fetch:

`GET /api/v1/appointments/doctor/queue`

Expected:

- Only paid, pending, unassigned `general_queue` appointments appear.
- Patient name and patient ID are absent.
- Prior clinical records and prescriptions are absent.
- Submitted triage text is limited to 500 characters.

### Inactive doctor queue access

Use an inactive doctor account to fetch or claim the queue.

Expected:

- Request is rejected.

### Valid claim

Set Doctor A as available and claim a paid, pending, unassigned general queue
appointment.

Expected:

- Request succeeds.
- Appointment is assigned to Doctor A.
- Status becomes `confirmed`.

Verify rejection when any condition is false:

- Type is not `general_queue`
- Status is not `pending`
- Payment is not `paid`
- Doctor is already assigned
- Slot is present
- Doctor is unavailable

Expected:

- Request returns `409`.
- Appointment remains unchanged.

### Concurrent claim

Send claim requests for the same appointment concurrently as Doctor A and
Doctor B.

Expected:

- Exactly one request succeeds.
- The other returns `409 Conflict`.
- The final appointment has exactly one assigned doctor.

## Specialist booking

Authenticate as a patient and book a future slot owned by an active specialist.

Expected:

- Appointment type is `specialist_scheduled`.
- Doctor is derived from the slot.
- Patient is the authenticated caller.
- Payment status starts as `unpaid`.

Attempt to book:

- An already booked slot
- A past slot
- A slot with no valid doctor
- A slot owned by an inactive specialist
- The same slot concurrently from two patients

Expected:

- Invalid requests return `409` or the documented integrity error.
- At most one appointment owns the slot.

## Consultation room lock

Use a paid, confirmed specialist appointment with a known future start time.
Test as both the owning patient and assigned doctor.

At more than 10 minutes before the start, attempt:

- `GET /api/v1/p2p/history/{appointment_id}`
- WebSocket `/api/v1/p2p/live/{appointment_id}/{user_id}`
- `GET /api/v1/video/token/{appointment_id}`

Expected:

- History and video requests return `423 Locked`.
- The WebSocket closes with code `4423`.
- No chat message is stored and no Agora token is issued.

Repeat at exactly 10 minutes before the start.

Expected:

- The patient and assigned doctor can enter the room.
- Flutter room buttons unlock without requiring a page reload.

Repeat using an unrelated authenticated user and a forged WebSocket `user_id`.

Expected:

- Direct HTTP requests return `403`.
- The WebSocket closes with `4403`.
- No room data, messages, or video token are exposed.

## Legacy appointment types

Attempt to claim an assigned/no-slot legacy appointment whose durable
`appointment_type` is `NULL`.

Expected:

- Request is rejected.
- The record is not guessed to be a general queue appointment.

Review and classify ambiguous legacy rows before making `appointment_type`
non-null.

## Remaining TODOs

- Run and verify `migrations/add_appointment_type.sql`.
- Review ambiguous legacy appointment rows.
- Make `appointment_type` non-null after all rows and writers are safe.
- Add automatic expiry and slot release for abandoned unpaid specialist bookings.
- Bind verified payment reference, patient, amount, currency, appointment type,
  and payable state before provider code marks an appointment paid.
- Convert this checklist into automated endpoint and concurrency tests.
