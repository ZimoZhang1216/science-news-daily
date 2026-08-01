# Manual User Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a confirmed per-user manual-send action that immediately generates and emails a personalised daily without changing its recurring schedule.

**Architecture:** A repository method atomically creates or reuses one manual-send delivery per user-local date. An opaque repository-dispatch command conditionally claims it and uses the existing report/PDF/SMTP path. The dashboard exposes the control only for active users.

**Tech Stack:** Python 3.14, SQLite/libsql, Streamlit, GitHub Actions, SMTP, unittest.

## Global Constraints

- The key is `manual_send:<user_id>:<YYYY-MM-DD>:email`, using the user's IANA time zone.
- Repeated clicks reuse an existing task and never add another mail attempt.
- The manual delivery has an empty `schedule_id`, so it cannot advance scheduled timings.
- The confirmation, dispatch payload, and tests must not expose email addresses, credentials, or profile content.

---

### Task 1: Create or reuse the immediate delivery

**Files:** `personalization/repository.py`, `tests/test_personalization_repository.py`

**Interface:** `create_manual_send(user_id: str, now_utc: datetime) -> DeliveryClaim` returns `created=True` only for the first task that day.

- [x] Write failing tests for local-date calculation, repeated-click reuse, empty schedule ID, and paused-user rejection.
- [x] Run `tests.test_personalization_repository` and verify `create_manual_send` is missing.
- [x] Implement the method inside the existing transaction: load an active user's time zone, derive their local date, insert a manual report run and queued delivery with the fixed key and empty `schedule_id`; return the existing row after a unique-key conflict.
- [x] Rerun repository tests and commit as `feat: create idempotent manual send deliveries`.

### Task 2: Run the immediate delivery safely

**Files:** `personalization/custom_runner.py`, `custom_user_daily.py`, `tests/test_custom_runner.py`, `tests/test_github_dispatch.py`

**Interface:** `deliver_manual_send(repository, delivery_id, services, now_utc=None) -> int` and `custom_user_daily.py deliver --delivery-id <id>`.

- [x] Write failing tests proving a manual delivery sends one mocked PDF, does not change `next_run_at`, and that the parser accepts `deliver`.
- [x] Run the focused runner/parser tests and verify red.
- [x] Conditionally claim only queued manual deliveries without `schedule_id`, delegate to the existing generation/PDF/SMTP function, and route the new CLI command without exposing profile or recipient data.
- [x] Rerun focused tests and commit as `feat: execute manual user deliveries`.

### Task 3: Dashboard confirmation and workflow command

**Files:** `personalization/github.py`, `.github/workflows/custom-user-daily.yml`, `dashboard/views.py`, `tests/test_github_dispatch.py`, `tests/test_dashboard_smoke.py`

**Interface:** `dispatch_command(settings, "deliver", delivery_id)` emits only the `command` and opaque `delivery_id` payload.

- [x] Write failing tests for `deliver` dispatch validation, workflow command, active-user button, confirmation, and absent paused-user button.
- [x] Run dashboard/dispatch tests and verify red.
- [x] Add a `deliver` Actions job with existing PDF dependencies, add the confirmation-gated dashboard button, and dispatch only when `create_manual_send(...).created` is true; existing tasks show status instead.
- [x] Rerun focused tests and commit as `feat: add confirmed manual send control`.

### Task 4: Documentation and verification

**Files:** `README.md`, `docs/superpowers/plans/2026-07-30-manual-user-delivery.md`

- [x] Document active-user-only confirmation, one immediate task per user-local day, no schedule advancement, and retry/termination visibility.
- [x] Run the full unittest suite, compile the modified Python files, and run `git diff --check`.
- [x] Mark plan tasks complete and commit as `docs: document manual user delivery`.
