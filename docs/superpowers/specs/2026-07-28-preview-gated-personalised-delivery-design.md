# Preview-gated personalised delivery design

## Goal

Make personalised research-daily onboarding safe and guided:

1. The operator supplies only the mandatory user facts.
2. The configured model produces a detailed, editable research-profile recommendation.
3. The system generates a preview without sending email.
4. After the operator approves the preview, the schedule is enabled for the next future scheduled time only.

The existing subject workflows and their fixed-recipient behaviour remain unchanged.

## Mandatory operator input

- Display name
- Recipient email address
- Research direction or current project

## Recommended but editable fields

The recommendation contains:

- Base report profile
- Include and exclude keywords
- Supported sources and supported journal ISSNs
- Content preferences
- Per-report item limit and output formats
- Model provider and model
- Frequency, weekday where relevant, timezone, and local send time

The default schedule is daily at `07:30` in `Asia/Shanghai`. The default model provider and model are resolved from the project's configured provider; the dashboard must not hard-code OpenAI as its default.

## Recommendation boundary

Recommendation runs in the local dashboard before a user profile is persisted. It calls the configured model once with a structured prompt and validates a JSON response against the existing supported profile, source, preference, format, and journal catalogues. The UI displays the recommendation and a concise rationale or uncertainty note, but the operator can change every recommended value.

The recommender may not invent journal ISSNs. Its journal choices are constrained to the journal metadata already supported by `main.REPORT_PROFILES`.

If the model call or structured validation fails, the dashboard must show a clear error and leave the operator's mandatory input intact. It must not create a user, enqueue a preview, or enable a schedule.

## State and delivery flow

```text
Mandatory inputs
  -> model recommendation (editable)
  -> save reviewed profile with schedule disabled
  -> manual preview workflow (email disabled)
  -> preview-ready artifact
  -> operator enables schedule
  -> first future scheduled run
  -> automatic report generation and email
```

The existing `schedules.enabled` field is the activation gate. A reviewed profile is saved with `enabled = false`; it is therefore not returned by the existing due-schedule query. This avoids a schema migration and keeps active/paused user state semantics intact.

When the operator chooses **Enable schedule** after `preview_ready`:

- The preview PDF is not emailed.
- The existing manual preview remains an artifact for review only.
- The schedule is enabled.
- `next_run_at` is recomputed as a time strictly later than activation time.
- The existing 15-minute `custom-user-daily.yml` scan delivers the first automatic report at that next run.

No dashboard action may enable a schedule before a successful preview exists. Existing users may continue to use their current edit, pause, resume, manual-preview, and retry paths.

## Reused implementation paths

- Dashboard: `dashboard/app.py` and `dashboard/views.py`
- State: `personalization/repository.py` and existing Turso/SQLite schema
- Generation: `main.generate_report`
- PDF: `main.convert_docx_to_pdf`
- Email: `main.send_report_email`
- Workflow runner: `personalization/custom_runner.py`
- GitHub Actions: `.github/workflows/custom-user-daily.yml`

The manual preview workflow remains email-free. Automatic delivery keeps the current AI-required, PDF-required, SMTP-required behaviour.

## Error handling and auditability

- Recommendation failure: no state change; show a retryable operator error.
- Preview failure: schedule stays disabled; delivery is recorded as retryable failed.
- Enable-schedule request without `preview_ready`: reject without state change.
- Automatic delivery failure: preserve the existing retry and lease-recovery rules.
- Record events for recommendation completion, preview creation, and schedule activation so the operations page can explain why a user is or is not scheduled.

## Verification

- Unit tests for recommendation validation, configured-provider defaults, and unsupported journal rejection.
- Repository tests proving a disabled schedule is not due and approval computes a future `next_run_at`.
- Runner test proving a preview does not send email and enabling a plan does not send that preview.
- Dashboard smoke tests for Chinese mandatory/optional labels and disabled-to-enabled state transitions.
- Existing full suite, dashboard render checks, workflow YAML parsing, and desktop/mobile browser checks.
