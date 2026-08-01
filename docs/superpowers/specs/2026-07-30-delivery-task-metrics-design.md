# Delivery Task Metrics Design

## Goal

Show source-by-source collection health and the selection funnel inside every personalised delivery record on the local Streamlit dashboard at port 8501. Operators must be able to explain a generated, failed, or retrying task without correlating a separate global metrics screen.

## Data model

The feature reuses the existing per-run tables instead of creating a second scheduler or an unbounded JSON event stream.

- `report_runs.candidate_count` stores the number of raw items returned by enabled sources.
- `report_runs.selected_count` stores the final number of items placed into the report.
- Add nullable-safe additive columns to `report_runs` for `matched_count` (after user-profile matching, including the existing base-profile fallback), `deduplicated_count` (after in-run duplicate collapse), and `history_excluded_count` (exact previous-report duplicates not selected).
- Existing `source_metrics` remains one row per source and run, including success flag, raw source count, and a bounded error summary.
- Existing delivery `last_error` and `error_stage` remain the canonical non-collection failure explanation (AI, Word, PDF, email, etc.).

The custom runner records report metrics and source statuses immediately after the generator returns, before PDF conversion or email. Consequently a failed task retains diagnostics from any collection work that completed. Failed before a generator result shows its delivery-stage error and an explicit no-metrics state.

## Pipeline semantics

`main.generate_report` returns a compact `ReportGenerationResult` with:

1. `collected_count`: all items returned by source collectors;
2. `matched_count`: items matching the saved user profile; if zero matches trigger the existing fallback, this is the fallback count and `profile_filter_fallback` is true;
3. `deduplicated_count`: unique items after duplicate collapse in the matching pool;
4. `history_excluded_count`: exact previous-report repeats left out of the selection when alternatives exist;
5. `selected_count`: final ranked report entries.

No titles, e-mail addresses, API keys, or raw profile text are copied into the metrics payload.

## Dashboard behaviour

Each entry in `日报与投递` has a `任务详情` expander containing:

- a five-stage count funnel;
- a visible note when the profile-matching fallback was used;
- a compact table of that task's source names, success/failure state, raw item count, and bounded failure reason;
- delivery failure stage/reason and next retry time when applicable;
- a clear compatibility message for historical task records created before metric persistence.

The standalone `数据源与指标` page remains an aggregate operational view; it is not removed or made the only place to inspect a task.

## Compatibility and verification

`report_runs` receives only additive columns with `0`/empty defaults through the repository's existing SQLite/libsql migration helper, so existing SQLite databases and Turso rows remain valid. Unit tests cover metric persistence on success and generator failure, task-scoped source lookups, dashboard rendering, and legacy rows with no metric data. Tests use mocked generators and do not send email or call a model.
