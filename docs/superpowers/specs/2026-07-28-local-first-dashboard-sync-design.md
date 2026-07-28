# Local-First Dashboard Sync Design

## Goal

Make the local Streamlit operations dashboard responsive during normal navigation while preserving Turso as the shared source of truth for GitHub Actions delivery jobs.

## Confirmed operating model

- The dashboard is operated by one administrator on this Mac.
- Fresh cloud status is only required when the administrator explicitly requests it.
- The dashboard does not poll Turso or synchronize while the administrator changes pages.
- The existing libsql Embedded Replica keeps reads local, but sends writes directly to Turso primary. Creating a preview or enabling a schedule therefore persists to the shared primary before GitHub Actions can act on it.
- Existing fixed-subject reports, the custom-user workflow, DeepSeek, SMTP, preview approval, and delivery idempotency remain unchanged.

## Architecture

The dashboard uses a libsql embedded replica stored outside the repository. Normal page reads use that local SQLite-compatible file. Turso remains the primary database used by GitHub Actions.

```text
Streamlit page navigation -> local libsql replica -> local SQLite reads
"Sync current status" -> replica.sync() -> Turso primary -> refreshed local replica
Profile, preview, schedule, or status write -> Turso primary -> GitHub Actions can read it
```

`PERSONAL_ADMIN_LOCAL_DB` remains a pure local development mode for tests and offline development. In production, when Turso credentials are present, the dashboard opens the replica at `PERSONAL_ADMIN_REPLICA_PATH` or a macOS application-support default. It does not automatically synchronize on startup: the first successful manual sync establishes the readable data. If the connected primary is empty, that administrator-initiated sync also bootstraps the project's existing schema before refreshing the replica. Streamlit resource caching keeps the connection out of page reruns.

## Interaction model

- The sidebar displays the current data mode and a single `同步当前状态` button when a replica is active.
- A successful synchronization displays the last synchronization time for the current dashboard process.
- A synchronization failure leaves cached data visible and displays a non-sensitive warning. It must not replace the page with a generic database-unavailable state.
- Profile edits, schedule edits, and status changes are saved directly to Turso; the next manual sync updates what the dashboard reads locally.
- Preview creation and schedule activation remain explicit administrator actions. GitHub dispatch uses the primary record that the write has already created.

## Failure handling

- Existing replica data remains readable if Turso is temporarily unreachable.
- Before the first successful synchronization, the dashboard presents a clear, retryable empty state and does not issue queries against a schema-less local file.
- Manual synchronization errors are bounded to the requested action and do not prevent navigation.
- GitHub Actions never reads the local replica; it continues to connect to Turso directly.

## Test strategy

- Unit-test the repository's replica connection and explicit synchronization capability using a fake libsql connection.
- Unit-test that dashboard repository creation is cached and does not repeat schema initialization during reruns.
- Test that startup does not contact Turso, that a manual sync makes the local schema readable, and that failure exposes no secret values.
- Extend Streamlit smoke tests for the visible synchronization control, a schema-less first-run state, and normal GitHub-dispatch paths.
- Run the existing test suite, compile checks, workflow YAML parsing, and browser verification of navigation plus manual synchronization UI.
