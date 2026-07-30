# Task 1 Implementation Report: Idempotent Manual Send Deliveries

## Scope

Implemented only Task 1 from the approved manual user delivery plan:

- `personalization/repository.py`
- `tests/test_personalization_repository.py`

## Implementation

Added `PersonalizationRepository.create_manual_send(user_id, now_utc)`.

- It runs inside the repository's existing transaction boundary.
- It reads the active user's saved schedule time zone and current profile version.
- It converts the supplied UTC instant to that user-local report date.
- It creates a queued manual `report_run` and email `delivery` keyed as
  `manual_send:<user_id>:<YYYY-MM-DD>:email`.
- It explicitly persists an empty `schedule_id`, so the later delivery cannot consume or advance a recurring schedule period.
- `ON CONFLICT(idempotency_key) DO NOTHING` preserves the first delivery. The temporary report run created by a repeated click is deleted, then the existing delivery is returned with `created=False`.
- Paused, expired, missing, or otherwise non-active users are rejected before any report run or delivery is created.

## Tests added

The repository tests now cover:

1. User-local date calculation at the Asia/Shanghai day boundary and the exact idempotency key.
2. Empty `schedule_id` for the immediate delivery.
3. Same-user repeated clicks within one local day reusing exactly one delivery and report run.
4. Paused-user rejection with no created delivery.

## TDD evidence

1. Before implementation, `.venv/bin/python -m unittest tests.test_personalization_repository -v` ran 30 tests and produced four expected `AttributeError` failures because `create_manual_send` did not exist.
2. After the minimal implementation, the same command passed all 30 tests.
3. The fixed-key assertion was mutation-checked by temporarily changing the key prefix to `manual_send_invalid`. Its focused test failed with the expected key mismatch; the production key was restored.
4. Final fresh verification ran `.venv/bin/python -m unittest tests.test_personalization_repository -v`: 30 tests passed.
5. `git diff --check` completed cleanly.

## Self-review

- SQLite/libsql compatibility is preserved by using the repository's existing portable transaction and `ON CONFLICT ... DO NOTHING` pattern.
- The implementation does not read, log, or add any credentials, addresses, or profile content to dispatch-facing data.
- Existing preview and automatic-delivery paths are untouched.
- No known concerns within Task 1 scope.
