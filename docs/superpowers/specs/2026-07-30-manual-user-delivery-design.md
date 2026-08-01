# Manual User Delivery Design

## Goal

Allow an operator to manually send a personalised research daily for any active user from the local dashboard without changing that user's recurring schedule.

## User flow

1. Each active user row exposes `手动发报`.
2. Clicking it opens an explicit confirmation that states it will generate a new PDF and email it to that user now.
3. Confirmation atomically creates or reuses an immediate manual delivery for the user's current local calendar date.
4. The dashboard dispatches a new `deliver` command to the existing `Custom User Research Daily` workflow.
5. The workflow claims the queued delivery, generates with the immutable profile version stored on that delivery, converts to PDF, and sends through the existing SMTP path.
6. The task remains visible in `日报与投递`, including metrics, status, errors, retry state, and the existing termination control.

## Delivery semantics and safety

- The immediate delivery uses a distinct `manual_send:<user_id>:<local_date>:email` database idempotency key. Repeated clicks for the same user and local date return the same delivery instead of creating another email attempt.
- A `sent`, `claimed`, `sending`, or `queued` manual-send delivery is never re-dispatched by the button. A retryable failure stays visible and is retried through the existing retry action.
- The report date is computed in the user's IANA time zone, not the dashboard machine's time zone.
- The delivery has no `schedule_id`; success therefore does not update `last_run_at` or `next_run_at` and cannot consume the scheduled daily period.
- The runner reuses the same bounded generation, PDF, mail preparation, `sending` ambiguity marker, and SMTP duplicate-prevention behaviour as automatic delivery. It does not attempt to download or resend a possibly expired preview artifact.
- Only `active` users are eligible. Paused and expired users do not get a send control.

## Implementation boundaries

- Add a repository method that atomically creates/reuses the immediate delivery and returns its current status.
- Add a `deliver` dispatch command and workflow job. The command receives only a delivery ID, never an email address or profile content.
- Add a manual-send runner entry that conditionally claims a queued manual delivery and delegates to the existing generation-and-email function.
- Extend retry routing so a failed immediate manual send retries delivery rather than regenerating a preview.
- Keep preview creation, preview confirmation, automatic scheduling, fixed-subject dailies, and their existing workflows unchanged.

## Verification

Network-free tests will cover user-local date selection, idempotent repeated clicks, inactive-user rejection, no schedule advancement, dispatch/workflow command contract, successful mocked SMTP delivery, retry routing, and dashboard confirmation/control visibility. No test sends an actual email or calls a paid model.
