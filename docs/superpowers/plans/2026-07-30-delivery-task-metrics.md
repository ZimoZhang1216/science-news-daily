# Delivery Task Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Make per-generation source counts, selection counts, and failure diagnostics visible in each personalised delivery detail at `127.0.0.1:8501`.

**Architecture:** Extend the existing `ReportGenerationResult`, `report_runs`, and `source_metrics` records. Persist diagnostics immediately after generation returns; render a task-scoped detail expander in the existing delivery page.

## Task 1: Add tests that define task-scoped metrics

**Files:** `tests/test_custom_runner.py`, `tests/test_personalization_repository.py`, `tests/test_dashboard_smoke.py`

- [x] Add a generator test asserting successful previews persist raw/matched/deduplicated/history-excluded/selected counts plus source records.
- [x] Add a failure test asserting a generator failure still persists available source diagnostics.
- [x] Add repository and dashboard tests asserting one delivery reads only its own source metrics and renders the task-detail labels.
- [x] Run the focused tests and verify they fail because task metrics are not yet persisted/exposed.

## Task 2: Produce and persist collection metrics

**Files:** `main.py`, `personalization/schema.sql`, `personalization/repository.py`, `personalization/custom_runner.py`

- [x] Compute matching, in-run deduplication, and exact-history exclusion counts without changing report-selection behaviour.
- [x] Add SQLite/Turso-safe report-run columns and a repository method that atomically updates run metrics and replaces only that run's source statuses.
- [x] Record metrics immediately after the generator returns, including failed generation results.
- [x] Run the focused runner and repository tests.

## Task 3: Render task details in the dashboard

**Files:** `dashboard/views.py`, `tests/test_dashboard_smoke.py`

- [x] Return task metrics in `list_recent_deliveries` and render the existing task status/actions unchanged.
- [x] Add a concise `任务详情` expander with a five-count funnel, fallback message, task-scoped source table, and existing failure/retry details.
- [x] Preserve a clear empty state for historical records.
- [x] Run dashboard smoke tests.

## Task 4: Verify, migrate, deploy, and document

**Files:** `README.md`, this plan

- [x] Document the per-task observability path and compatibility behaviour.
- [x] Run the complete test suite, Python compilation, and diff check.
- [x] Apply the additive migration to the configured Turso database if the new columns are absent; do not read or print credentials.
- [x] Restart the local Streamlit service on port 8501 from this latest worktree and perform a visual dashboard check.
- [x] Commit and push the reviewed change to the latest `main` branch.
