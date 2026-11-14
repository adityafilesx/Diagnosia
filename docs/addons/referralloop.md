# ReferralLoop

**Status:** pilot. Receivers must be verified, and verified organizations are required. Revoking consent ends receiver access.

Tracks a referral until the outcome is back and reviewed. It doesn't decide who needs one.
Code: `backend/referralloop/`, `web/js/care/referrals.js`. Tests: `test_referralloop.py`.

## Stages

`sent` → `acknowledged` → `accepted` → `appointment_offered` → `booked` → `attended` →
`outcome_returned` → `closed`.

Also `needs_information`, `declined`, `redirected`, `rescheduled`, `no_show`, and
`cancelled`, which means closed without an outcome and always has a reason.

Moves are checked by side. The receiver moves most stages, the referrer resends after
a request for information, reviews the outcome and closes. For phone, fax or paper
referrals, the referrer records the receiver's steps, marked `manual`.

A `redirected` or `declined` referral is replaced, not edited: the referrer sends a new referral that
names it in `replaces_referral_id` (the screen copies the reason, question, priority and documents and
asks only where to send it). The old one then closes as `cancelled` with the reason "Replaced by a new
referral", and each links to the other (`replaced_by` and `replaces`, shown to the referrer only). It
skips the duplicate question, because it takes over from the open one. A referral still in progress is
not closed this way.

A referral whose outcome is back (`outcome_returned`) can't be closed without one: `POST /{id}/close`
is refused with a 409, and reviewing the outcome is the only way to close it.

A referral is `booked` only with an appointment: moving to `booked` marks the newest open
appointment (offered, booked or rescheduled) as the booking, and is refused with a 409 when there is
none, as after a missed visit. An appointment time must be a real date, or a date and time, within a
year back and three years ahead; anything else is refused with a 422. It is stored as `YYYY-MM-DD` or
`YYYY-MM-DDTHH:MM`.

## Scenario coverage

Toolkit scenarios TS-01 and TS-03 to TS-08 are automated. TS-02 (prior authorization)
is left out as a US payer step.

## Data

`referrals`, `referral_events` (the history), `referral_documents`,
`referral_appointments`, `referral_outcomes`.

## API

Under `/api/addons/referrals`: `POST /`, `GET inbox`, `GET sent`, `GET exceptions`,
`GET patients/{id}`, `GET /{id}`, `POST /{id}/acknowledge`, `PATCH /{id}/status`,
`POST /{id}/priority`, `POST /{id}/appointments`, `POST /{id}/contact-attempts`,
`POST /{id}/outcome`, `POST /{id}/review`, `POST /{id}/close`.

## Safety

- `referral_sharing` consent is required to send, and revoking it ends the receiver's access.
- A receiver sees the referral and chosen files, not the patient's record.
- Priority and response dates are set by people, never from free text. The form's date
  is only a starting value.
- Urgent referrals sort first in the inbox.
- A returned outcome becomes a task for the referrer, not a passive chart entry.
- Declined and unanswered referrals stay in the "needs chasing" queue.
- Three failed contact attempts alert the referrer. A duplicate within 30 days needs
  a reason.

## Limits

Response times aren't defined per service. There is no routing by availability, no
external messaging, and the directory is every organization on this installation.
