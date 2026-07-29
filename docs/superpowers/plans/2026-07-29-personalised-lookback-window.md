# Personalised Lookback Window Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let every user profile select a one-to-sixty-day information lookback window, with a backwards-compatible three-day default.

**Architecture:** Store `lookback_days` in immutable research-profile versions, migrate the additive database column for SQLite and Turso, and let the runner read the saved profile value when creating `ReportGenerationOptions`. Render the same validated field in onboarding and editing.

**Tech Stack:** Python 3.14, SQLite/libsql (Turso), Streamlit, unittest.

## Global Constraints

- `lookback_days` accepts integers from 1 through 60 inclusive; the default is 3.
- Existing users, schedules, deliveries, fixed-subject workflows, and history-deduplication behaviour remain unchanged.
- Do not log raw user profile text, email addresses, or secrets.

---

### Task 1: Profile contract and additive migration

**Files:**
- Modify: `personalization/models.py`
- Modify: `personalization/schema.sql`
- Modify: `personalization/repository.py`
- Modify: `tests/test_personalization_models.py`
- Modify: `tests/test_personalization_repository.py`

**Interfaces:**
- Produces: `ResearchProfileInput.lookback_days: int`.
- Consumes: `ResearchProfileInput.from_form(..., lookback_days: int = 3)`.

- [ ] **Step 1: Write failing boundary and migration tests**

```python
self.assertEqual(self.valid_profile(lookback_days=60).lookback_days, 60)
with self.assertRaisesRegex(ValueError, "lookback_days"):
    self.valid_profile(lookback_days=61)
```

Create a legacy `research_profiles` table without the new column, call
`repository.initialize()`, and assert the existing row reads back with
`lookback_days == 3`.

- [ ] **Step 2: Run the focused tests to verify red**

Run: `.venv/bin/python -m unittest tests.test_personalization_models tests.test_personalization_repository -q`

Expected: failures because the field and migration do not exist.

- [ ] **Step 3: Add the validated field and migration**

Add `lookback_days` to `ResearchProfileInput`, validate `1 <= value <= 60`,
add `lookback_days INTEGER NOT NULL DEFAULT 3` to the fresh schema, add an
`_add_column_if_missing("research_profiles", "lookback_days", "INTEGER NOT NULL DEFAULT 3")`
migration, and include the field in repository profile reads and inserts.

- [ ] **Step 4: Run the focused tests to verify green**

Run: `.venv/bin/python -m unittest tests.test_personalization_models tests.test_personalization_repository -q`

Expected: all targeted tests pass.

### Task 2: Use the saved window in the personalised runner

**Files:**
- Modify: `personalization/custom_runner.py`
- Modify: `tests/test_custom_runner.py`

**Interfaces:**
- Consumes: `context.profile.input.lookback_days`.
- Produces: `ReportGenerationOptions.days` equal to the saved profile value.

- [ ] **Step 1: Write a failing runner test**

```python
with mock.patch.dict(os.environ, {"CUSTOM_REPORT_DAYS": "1"}):
    generate_preview(repository, delivery_id, services)
self.assertEqual(captured_options.days, 60)
```

The fixture profile must set `lookback_days=60`; the test proves the profile
value wins over the obsolete environment setting.

- [ ] **Step 2: Run the focused test to verify red**

Run: `.venv/bin/python -m unittest tests.test_custom_runner -q`

Expected: failure because `_generation_options()` still reads
`CUSTOM_REPORT_DAYS`.

- [ ] **Step 3: Replace the personalised environment lookup**

Set `ReportGenerationOptions.days=context.profile.input.lookback_days` and
retain `_positive_env_int` for the other runner limits that still use it.

- [ ] **Step 4: Run the focused test to verify green**

Run: `.venv/bin/python -m unittest tests.test_custom_runner -q`

Expected: all custom-runner tests pass.

### Task 3: Dashboard controls and recommendation default

**Files:**
- Modify: `dashboard/views.py`
- Modify: `personalization/recommender.py`
- Modify: `tests/test_dashboard_smoke.py`
- Modify: `tests/test_personalization_recommender.py`

**Interfaces:**
- Consumes: `ResearchProfileInput.lookback_days`.
- Produces: a `资讯时间窗口（天）` integer input with values 1–60.

- [ ] **Step 1: Write failing UI and recommendation tests**

```python
self.assertIn("资讯时间窗口（天）", source)
self.assertEqual(recommendation.profile.lookback_days, 3)
```

- [ ] **Step 2: Run the focused tests to verify red**

Run: `.venv/bin/python -m unittest tests.test_dashboard_smoke tests.test_personalization_recommender -q`

Expected: the dashboard label is absent and recommendation profiles lack the
field.

- [ ] **Step 3: Render and persist the control**

Add `st.number_input("资讯时间窗口（天）", min_value=1, max_value=60, step=1)` to both
forms, defaulting to the recommended/current profile value. Pass it through
`ResearchProfileInput.from_form`; set the recommender-built profile to the
default value of 3.

- [ ] **Step 4: Run the focused tests to verify green**

Run: `.venv/bin/python -m unittest tests.test_dashboard_smoke tests.test_personalization_recommender -q`

Expected: all dashboard and recommender tests pass.

### Task 4: Documentation and full regression verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document the per-user 1–60 day window**

State that it controls information collection only, defaults legacy profiles
to three days, and does not change scheduling or deduplication.

- [ ] **Step 2: Run full validation**

Run: `.venv/bin/python -m unittest discover -s tests -q`

Run: `.venv/bin/python -m py_compile personalization/models.py personalization/repository.py personalization/custom_runner.py personalization/recommender.py dashboard/views.py`

Run: `git diff --check`

Expected: all tests pass, compilation succeeds, and the diff has no whitespace
errors.

- [ ] **Step 3: Commit and push**

```bash
git add personalization dashboard tests README.md docs/superpowers
git commit -m "feat: add personalised lookback windows"
git push origin codex/unified-user-scheduler
git push origin HEAD:main
```
