# Personalised Information Lookback Window Design

## Goal

Let each personalised research-daily profile define how far back the runner
collects items, from one to sixty days. The default remains three days.

## Product decisions

- The field is named `lookback_days` and means the inclusive historical
  collection range before the report run time; it does not affect the
  recipient's local send time, schedule frequency, or report-history
  deduplication window.
- The dashboard renders it as an integer control labelled `资讯时间窗口（天）`
  with a minimum of 1, maximum of 60, and a default of 3.
- It belongs to `ResearchProfileInput`, so it is immutable for an already
  generated report and changes only when an operator saves a new profile
  version. Manual previews and subsequent automatic deliveries use the saved
  version's value.
- AI-assisted onboarding continues to recommend research topics, sources and
  keywords. It uses the conservative default of 3 days rather than allowing a
  model response to choose an operational range.

## Architecture

`research_profiles.lookback_days` is an additive non-null integer column with
database default `3`. The repository migration adds it for existing SQLite and
Turso databases, so legacy current profiles immediately read as three days.

The personalised runner passes `context.profile.input.lookback_days` into
`main.ReportGenerationOptions.days`. Fixed-subject reports retain their
existing command-line and environment configuration; the personalised runner
no longer reads `CUSTOM_REPORT_DAYS`.

The dashboard exposes the same validated value in both onboarding and profile
editing forms. Saving an edit creates the established immutable profile version
and leaves schedules and delivery history unchanged.

## Compatibility and failure behaviour

- Values below 1 or above 60 are rejected at the shared input boundary before
  a database write or workflow dispatch.
- Existing database rows receive the default value through the migration;
  existing users continue to receive three-day reports until an operator saves
  a different window.
- A database migration race is treated like existing additive scheduler
  migrations: another process completing the same `ALTER TABLE` is harmless.
- No user emails, profile text or model responses are written to logs.

## Test plan

- Validate the accepted 1-day and 60-day bounds and reject 0 and 61.
- Verify a saved profile round-trips its window and a legacy schema receives
  `lookback_days=3` without losing profile data.
- Verify the personalised runner uses the profile value rather than
  `CUSTOM_REPORT_DAYS`.
- Verify onboarding and editing render the time-window control.
- Run the full unittest suite without real SMTP, model calls, or network
  requests.

## Non-goals

- No change to the external cron wake-up cadence, user schedule frequency,
  local delivery time, automatic retry cadence, or history deduplication
  duration.
- No arbitrary date-range picker or time-of-day collection cutoff in this
  change.
