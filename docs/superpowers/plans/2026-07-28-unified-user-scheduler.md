# Unified User Scheduler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Use one external `science-news-daily` dispatch workflow to run unchanged fixed reports and bounded, database-backed personalised report deliveries every 30 minutes.

**Architecture:** Keep the existing personalisation repository and report generator. Extend its schema through idempotent migrations, use conditional database updates to claim work, and make delivery state durable through generation, PDF, SMTP and final confirmation. The existing cronjob workflow gains a separate user-scheduler job so the fixed-report marker never suppresses due-plan scans.

**Tech Stack:** Python 3.11+, sqlite3, Turso/libsql DB-API, `zoneinfo` and python-dateutil, GitHub Actions, unittest.

## Global Constraints

- Preserve the five fixed profiles, their recipients, date marker, artifacts, PDF conversion and `main.py` entry points.
- Use `repository_dispatch` event type `science-news-daily`; document an external cadence of every 30 minutes.
- Store timestamps as UTC ISO 8601 strings and retain local user display/schedule configuration.
- Do not log credentials or full user email addresses.
- Do not call real SMTP, OpenAI, DeepSeek or Turso in tests.
- Do not commit, push or alter existing worktrees without explicit user approval.

---

### Task 1: Freeze existing behavior and define scheduling tests

**Files:**
- Modify: `tests/test_personalization_repository.py`
- Modify: `tests/test_custom_runner.py`
- Create: `tests/test_unified_scheduler.py`

**Interfaces:**
- Produces expected APIs: `claim_due_delivery`, `recover_expired_deliveries`, `compute_next_run`, `run_due_deliveries` and `SchedulerSummary`.

- [ ] **Step 1: Add failing repository tests**

```python
def test_due_schedule_is_claimed_only_once_by_two_repository_connections(self):
    first = self.repository.claim_due_delivery(now, execution_id="worker-a")
    second = other_repository.claim_due_delivery(now, execution_id="worker-b")
    self.assertIsNotNone(first)
    self.assertIsNone(second)

def test_retryable_delivery_waits_for_next_retry_at(self):
    self.repository.mark_retryable_failure(delivery_id, "pdf", "conversion failed", now)
    self.assertIsNone(self.repository.claim_retry_delivery(now, "worker-a"))

def test_sending_lease_becomes_unknown_without_automatic_retry(self):
    self.repository.mark_email_sending(delivery_id, now)
    self.repository.recover_expired_deliveries(now + timedelta(hours=3), 120)
    self.assertEqual(self.repository.get_delivery(delivery_id).status, "failed")
```

- [ ] **Step 2: Add failing runner tests**

```python
def test_limit_leaves_additional_due_plans_for_the_next_scan(self):
    summary = run_due_deliveries(repository, now, services, max_jobs=1, deadline=deadline)
    self.assertEqual(summary.claimed, 1)
    self.assertTrue(summary.has_more_due)

def test_one_delivery_failure_does_not_stop_the_next_claim(self):
    summary = run_due_deliveries(repository, now, alternating_services, max_jobs=2, deadline=deadline)
    self.assertEqual(summary.failed, 1)
    self.assertEqual(summary.sent, 1)
```

- [ ] **Step 3: Add failing time-zone tests**

```python
def test_daily_schedule_uses_first_occurrence_of_ambiguous_dst_time(self):
    schedule = ScheduleInput.from_form("daily", None, "America/New_York", "01:30", True)
    self.assertEqual(compute_next_run(schedule, utc(2026, 11, 1, 4, 0)), utc(2026, 11, 1, 5, 30))

def test_daily_schedule_resolves_nonexistent_dst_time_forward(self):
    schedule = ScheduleInput.from_form("daily", None, "America/New_York", "02:30", True)
    self.assertEqual(compute_next_run(schedule, utc(2026, 3, 8, 5, 0)), utc(2026, 3, 8, 7, 30))
```

- [ ] **Step 4: Run the new tests and record expected failures**

Run: `.venv/bin/python -m unittest tests.test_personalization_repository tests.test_custom_runner tests.test_unified_scheduler -v`

Expected: failures due to missing conditional-claim, summary, retry timestamp and explicit DST behavior.

### Task 2: Add compatible schema migration and richer delivery records

**Files:**
- Modify: `personalization/schema.sql`
- Modify: `personalization/repository.py`
- Test: `tests/test_personalization_repository.py`

**Interfaces:**
- Produces `PersonalizationRepository.initialize()` migrations safe for existing SQLite and Turso databases.
- Produces `DeliveryRecord` fields `schedule_id`, `schedule_period_key`, `locked_at`, `locked_by`, `execution_id`, `next_retry_at`, `error_stage`, `email_prepared_at`, `email_sending_at`.

- [ ] **Step 1: Write migration tests**

```python
def test_initialize_migrates_a_pre_scheduler_schema_without_losing_delivery(self):
    legacy.execute("CREATE TABLE deliveries (... existing columns ...)")
    legacy.execute("INSERT INTO deliveries (...) VALUES (...)")
    repository.initialize()
    self.assertEqual(repository.get_delivery(existing_id).id, existing_id)
    self.assertIn("next_retry_at", repository.delivery_columns())
```

- [ ] **Step 2: Implement additive migration helpers**

```python
def _migrate_schema(self) -> None:
    self._ensure_table("schema_migrations")
    self._add_column_if_missing("deliveries", "next_retry_at", "TEXT NOT NULL DEFAULT ''")
    self._add_column_if_missing("deliveries", "locked_at", "TEXT NOT NULL DEFAULT ''")
    # add every documented delivery column, then create supporting indexes
```

Run: `.venv/bin/python -m unittest tests.test_personalization_repository -v`

- [ ] **Step 3: Extend row parsing and records**

```python
@dataclass(frozen=True)
class DeliveryRecord:
    # existing fields
    next_retry_at: datetime | None
    error_stage: str
    execution_id: str
```

Run: `.venv/bin/python -m unittest tests.test_personalization_repository -v`

### Task 3: Implement period-key idempotency and atomic due-work claims

**Files:**
- Modify: `personalization/repository.py`
- Test: `tests/test_personalization_repository.py`

**Interfaces:**
- Produces `enqueue_automatic_delivery(due, now_utc) -> DeliveryClaim` with a schedule-period key.
- Produces `claim_delivery(delivery_id, execution_id, now_utc)` and `claim_next_due_delivery(now_utc, execution_id)` that return `None` unless their conditional update changed one row.

- [ ] **Step 1: Run the concurrent-claim regression test from Task 1**

Run: `.venv/bin/python -m unittest tests.test_personalization_repository.PersonalizationRepositoryTests.test_due_schedule_is_claimed_only_once_by_two_repository_connections -v`

Expected: FAIL before conditional update implementation.

- [ ] **Step 2: Implement atomic lifecycle operations**

```sql
UPDATE deliveries
SET status = 'claimed', attempt_count = attempt_count + 1,
    locked_at = ?, locked_by = ?, execution_id = ?, updated_at = ?
WHERE id = ? AND status IN ('queued', 'retryable_failed')
  AND (next_retry_at = '' OR next_retry_at <= ?)
```

Use `cursor.rowcount` or a post-update `SELECT` constrained by `execution_id`; only the winner receives a claim. In the same enqueue transaction, insert the period key with `ON CONFLICT(idempotency_key) DO NOTHING`, preserve the existing row on conflict, and advance `schedules.next_run_at` to the first future runtime relative to scan time.

- [ ] **Step 3: Verify idempotency and SQLite concurrency**

Run: `.venv/bin/python -m unittest tests.test_personalization_repository -v`

### Task 4: Add time-zone and missed-run scheduling rules

**Files:**
- Modify: `personalization/repository.py`
- Test: `tests/test_personalization_repository.py`

**Interfaces:**
- Produces `compute_next_run(schedule, reference_utc)` with explicit first-fold and forward-resolved DST policy.

- [ ] **Step 1: Run the DST tests from Task 1**

Run: `.venv/bin/python -m unittest tests.test_unified_scheduler.UnifiedSchedulerTimeTests -v`

Expected: FAIL before explicit resolution.

- [ ] **Step 2: Implement local-time resolution and future-only advancement**

```python
def _resolve_local_schedule_time(local_date: date, schedule: ScheduleInput) -> datetime:
    candidate = datetime.combine(local_date, schedule.local_send_time, ZoneInfo(schedule.timezone)).replace(fold=0)
    return resolve_imaginary(candidate)
```

Use the resolved candidate for daily, weekdays and weekly selection. When a scan is late, enqueue the due period once and use `compute_next_run(schedule, now_utc)` for the next persisted runtime.

- [ ] **Step 3: Verify timezone, pause/resume, update-time and missed-run tests**

Run: `.venv/bin/python -m unittest tests.test_personalization_repository tests.test_unified_scheduler -v`

### Task 5: Add stage-aware failures, retry backoff and safe email boundary

**Files:**
- Modify: `personalization/repository.py`
- Modify: `personalization/custom_runner.py`
- Test: `tests/test_custom_runner.py`

**Interfaces:**
- Produces `mark_retryable_failure(delivery_id, stage, message, now_utc)`.
- Produces `mark_email_prepared`, `mark_email_sending`, `mark_sent` and stage-aware `recover_expired_deliveries`.

- [ ] **Step 1: Add failing stage and mail-boundary tests**

```python
def test_pdf_failure_records_pdf_stage_and_backoff(self): ...
def test_smtp_false_records_email_stage_and_retries_later(self): ...
def test_exception_after_mailer_is_not_automatically_resent(self): ...
```

- [ ] **Step 2: Implement stage transitions**

```python
repository.mark_email_prepared(claim.delivery_id, pdf_path, now_utc)
repository.mark_email_sending(claim.delivery_id, now_utc)
try:
    accepted = services.mailer(...)
except Exception as exc:
    repository.mark_retryable_failure(claim.delivery_id, "email", type(exc).__name__, now_utc)
else:
    repository.mark_sent(claim.delivery_id, now_utc) if accepted else repository.mark_retryable_failure(...)
```

Classify non-success report results from `main.generate_report` using source statuses and AI completion, then use `document`, `pdf` or `email` for subsequent boundaries.

- [ ] **Step 3: Verify retry and no-double-send behavior**

Run: `.venv/bin/python -m unittest tests.test_custom_runner tests.test_personalization_repository -v`

### Task 6: Add bounded scheduler summaries and CLI output

**Files:**
- Modify: `personalization/custom_runner.py`
- Modify: `custom_user_daily.py`
- Create: `tests/test_unified_scheduler.py`

**Interfaces:**
- Produces `SchedulerSummary(discovered, claimed, sent, skipped, failed, waiting_retry, recovered, has_more_due)`.
- Produces `run_due_deliveries(..., max_jobs, deadline) -> SchedulerSummary`.

- [ ] **Step 1: Run the batch and isolation tests from Task 1**

Run: `.venv/bin/python -m unittest tests.test_unified_scheduler.UnifiedSchedulerRunnerTests -v`

Expected: FAIL because current runner has no limits or summary.

- [ ] **Step 2: Implement bounded dispatch**

```python
max_jobs = _positive_env_int("MAX_JOBS_PER_RUN", 10)
deadline = now_utc + timedelta(minutes=_positive_env_int("MAX_RUNTIME_MINUTES", 80))
while summary.claimed < max_jobs and datetime.now(UTC) < deadline:
    claim = repository.claim_next_due_delivery(...)
    if claim is None:
        break
    process_claim_without_raising_to_batch(...)
```

The CLI writes one JSON summary line with counts only and returns non-zero if any claimed delivery failed; it must not print recipient addresses.

- [ ] **Step 3: Verify all scheduler-focused tests**

Run: `.venv/bin/python -m unittest tests.test_custom_runner tests.test_unified_scheduler -v`

### Task 7: Unify GitHub Actions scheduling while preserving manual controls

**Files:**
- Modify: `.github/workflows/cronjob-daily.yml`
- Modify: `.github/workflows/custom-user-daily.yml`
- Modify: `tests/test_github_dispatch.py`

**Interfaces:**
- Produces one automatic trigger: `science-news-daily` in `cronjob-daily.yml`.
- Retains `personal-news-command` only for manual preview/retry.

- [ ] **Step 1: Add static workflow regression tests**

```python
def test_only_cronjob_workflow_contains_an_automatic_schedule_trigger(self): ...
def test_cronjob_workflow_runs_custom_scan_even_when_fixed_marker_hits(self): ...
def test_cronjob_workflow_injects_turso_without_printing_it(self): ...
```

- [ ] **Step 2: Update workflow jobs**

Move the current automatic `scan` job out of `custom-user-daily.yml`; retain preview/retry jobs. Add a `user-scheduler` job to `cronjob-daily.yml` with Turso, SMTP and model secrets, Python/libreoffice setup, `MAX_JOBS_PER_RUN`, `MAX_RUNTIME_MINUTES`, and `CUSTOM_DELIVERY_LEASE_MINUTES`. It always runs for both dispatch and manual workflow invocations, independently of `.daily-run-marker`, writes a sanitized summary and uploads only user scheduler logs/artifacts.

- [ ] **Step 3: Verify workflow contracts**

Run: `.venv/bin/python -m unittest tests.test_github_dispatch -v`

### Task 8: Document operations and run full verification

**Files:**
- Modify: `README.md`
- Modify: `.env.example`
- Modify: `docs/superpowers/specs/2026-07-28-unified-user-scheduler-design.md`
- Test: all `tests/`

**Interfaces:**
- Documents the 30-minute external dispatch, new `TURSO_*` and scheduler limits, automatic retry boundary and operator action for unknown SMTP outcomes.

- [ ] **Step 1: Update operational documentation**

Add the single external dispatch payload, `*/30` cron example, required Turso Secrets, configurable limits and a privacy-safe diagnostic summary. Remove references to the retired automatic custom workflow schedule.

- [ ] **Step 2: Run complete test suite**

Run: `.venv/bin/python -m unittest discover -s tests -v`

Expected: all scheduler and existing non-Dashboard tests pass. Investigate the pre-existing Streamlit 1.60 timeout separately; do not mask it with scheduler changes.

- [ ] **Step 3: Validate generated YAML and CLI**

Run: `.venv/bin/python -m py_compile custom_user_daily.py personalization/repository.py personalization/custom_runner.py && .venv/bin/python custom_user_daily.py --help`

Expected: syntax succeeds and CLI lists `scan`, `preview`, `artifact-metadata`, `retry`.

## Plan self-review

- Schema migration, SQLite/Turso compatibility, atomic claiming, leases, retry/backoff, SMTP boundary, bounded execution, time zones/DST, fixed-flow isolation, tests and operational docs each have a corresponding task.
- The plan has no placeholder tasks; interface names are introduced before their use.
- The plan intentionally leaves dashboard visual changes and the pre-existing Streamlit 1.60 timeout outside this scheduling scope.
