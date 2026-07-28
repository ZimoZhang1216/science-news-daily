# Local-First Dashboard Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the personal dashboard read from a local replica and synchronize Turso only when the administrator explicitly requests a state refresh.

**Architecture:** `PersonalizationRepository` gains an explicit local-replica constructor and synchronous `sync()` capability. `dashboard/app.py` caches the repository per process, opens either the existing pure-local test database or a libsql embedded replica, and exposes manual sync state. `dashboard/views.py` keeps the existing direct-to-Turso writes and relies on the replica only for local reads.

**Tech Stack:** Python 3.11, Streamlit, libsql, SQLite-compatible repository, unittest, Streamlit AppTest.

## Global Constraints

- Keep Turso as the cloud primary used by GitHub Actions.
- Do not expose credentials in UI, logs, tests, or documentation.
- Preserve `PERSONAL_ADMIN_LOCAL_DB` behavior for existing tests and local development.
- Do not modify email, DeepSeek, PDF, delivery-idempotency, or fixed-subject workflow behavior.
- Do not automatically commit or push changes.

---

### Task 1: Add explicit replica connection and sync behavior

**Files:**
- Modify: `personalization/repository.py:147-184`
- Modify: `tests/test_personalization_repository.py`

**Interfaces:**
- Produces: `PersonalizationRepository.for_local_replica(path: Path, sync_url: str, auth_token: str) -> PersonalizationRepository`.
- Produces: `PersonalizationRepository.is_local_replica: bool`.
- Produces: `PersonalizationRepository.sync() -> bool`, returning `True` only when an explicit libsql replica synchronization was performed.

- [ ] **Step 1: Write failing replica tests**

```python
def test_local_replica_connection_uses_local_path_and_manual_sync(self) -> None:
    calls: list[object] = []
    connection = FakeReplicaConnection(calls)
    repository = PersonalizationRepository.for_local_replica(
        Path("/tmp/dashboard-replica.db"), "libsql://dashboard.example", "test-token"
    )
    self.assertTrue(repository.is_local_replica)
    self.assertTrue(repository.sync())
    self.assertEqual(calls[-1], "sync")

def test_plain_sqlite_repository_has_no_remote_sync(self) -> None:
    self.assertFalse(self.repository.sync())
```

- [ ] **Step 2: Run the focused test file and confirm the new replica test fails because the constructor is missing**

Run: `python3 -m unittest tests.test_personalization_repository.PersonalizationRepositoryTests.test_local_replica_connection_uses_local_path_and_manual_sync -v`

Expected: failure naming missing `for_local_replica`.

- [ ] **Step 3: Implement the minimal repository changes**

```python
@classmethod
def for_local_replica(cls, path: Path, sync_url: str, auth_token: str) -> "PersonalizationRepository":
    import libsql
    return cls(libsql.connect(database=str(path), sync_url=sync_url, auth_token=auth_token), is_local_replica=True)

def sync(self) -> bool:
    if not self.is_local_replica:
        return False
    self.connection.sync()
    return True
```

- [ ] **Step 4: Run focused repository tests and confirm they pass**

Run: `python3 -m unittest tests.test_personalization_repository -v`

Expected: all repository tests pass.

### Task 2: Cache the dashboard repository and open a replica in production

**Files:**
- Modify: `dashboard/app.py:1-42`
- Modify: `tests/test_dashboard_smoke.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: cached dashboard repository factory keyed by non-secret mode and database path.
- Produces: production default replica path overrideable by `PERSONAL_ADMIN_REPLICA_PATH`.

- [ ] **Step 1: Write failing dashboard factory tests**

```python
def test_replica_factory_initializes_once_and_reuses_the_same_repository(self) -> None:
    first = app_module.get_repository_or_none()
    second = app_module.get_repository_or_none()
    self.assertIs(first, second)
    self.assertEqual(fake_repository.initialize_calls, 1)

def test_existing_replica_remains_available_when_manual_sync_fails(self) -> None:
    repository = app_module.get_repository_or_none()
    with self.assertRaises(ConnectionError):
        repository.sync()
    self.assertIsNotNone(repository)
```

- [ ] **Step 2: Run the focused dashboard tests and confirm expected failures**

Run: `python3 -m unittest tests.test_dashboard_smoke -v`

Expected: factory/cache expectations fail before implementation.

- [ ] **Step 3: Implement cached local-first opening**

```python
@st.cache_resource(show_spinner=False)
def _open_repository(mode: str, database_path: str, sync_url: str) -> PersonalizationRepository:
    if mode == "local":
        repository = PersonalizationRepository.for_sqlite(Path(database_path))
    else:
        repository = PersonalizationRepository.for_local_replica(Path(database_path), sync_url, os.environ["TURSO_AUTH_TOKEN"])
    repository.initialize()
    return repository
```

Do not automatically call `sync()` while opening a replica. Detect whether the local replica already has the application schema; before the first successful manual sync, render a retryable empty state rather than querying a schema-less file.

- [ ] **Step 4: Add the documented non-secret path override**

Add `PERSONAL_ADMIN_REPLICA_PATH=` to `.env.example` with a comment explaining that it stores the local dashboard cache and must not be committed.

- [ ] **Step 5: Run focused dashboard tests and confirm they pass**

Run: `python3 -m unittest tests.test_dashboard_smoke -v`

Expected: all dashboard smoke tests pass.

### Task 3: Add visible manual synchronization

**Files:**
- Modify: `dashboard/app.py:34-42`
- Modify: `dashboard/views.py:149-670`
- Modify: `tests/test_dashboard_smoke.py`

**Interfaces:**
- Consumes: `repository.is_local_replica` and `repository.sync()`.
- Produces: a visible `同步当前状态` control and non-sensitive sync state.
- Produces: a clear first-run state that never queries a replica before its schema has been synchronized.

- [ ] **Step 1: Write failing Streamlit tests**

```python
def test_replica_mode_displays_a_manual_sync_button(self) -> None:
    app = self.replica_dashboard_app()
    self.assertIn("同步当前状态", [button.label for button in app.button])

def test_replica_without_a_completed_sync_shows_a_retryable_empty_state(self) -> None:
    app = self.replica_dashboard_app_without_schema()
    self.assertIn("本地副本尚未准备好", " ".join(info.value for info in app.info))
```

- [ ] **Step 2: Run focused smoke tests and confirm failures identify absent control/protection**

Run: `python3 -m unittest tests.test_dashboard_smoke -v`

Expected: the new tests fail before UI changes.

- [ ] **Step 3: Add sidebar state and manual sync**

Add a sidebar control that calls `repository.sync()` only after the user clicks it. Store the successful timestamp and non-sensitive failure class on the cached repository. Continue to render local data after failure; show a retryable empty state if no successful sync has established a schema yet.

Keep existing profile, preview, schedule, and status writes direct to Turso primary. Do not claim that local edits await upload: libsql Embedded Replica `sync()` refreshes local reads rather than publishing a local outbox.

- [ ] **Step 5: Run focused smoke tests and confirm they pass**

Run: `python3 -m unittest tests.test_dashboard_smoke -v`

Expected: all smoke tests pass, including manual-sync and schema-less first-run tests.

### Task 4: Verify local-first behavior and regressions

**Files:**
- Modify: `README.md` only if behavior/configuration text is now inaccurate.
- Modify: `docs/superpowers/specs/2026-07-28-local-first-dashboard-sync-design.md` only if implementation requires a documented design correction.

- [ ] **Step 1: Run all automated tests**

Run: `python3 -m unittest discover -s tests -v`

Expected: all tests pass.

- [ ] **Step 2: Run static checks**

Run: `python3 -m compileall dashboard personalization custom_user_daily.py`

Expected: exit code 0.

- [ ] **Step 3: Validate workflow YAML**

Run: `python3 -c 'import yaml; yaml.safe_load(open(".github/workflows/custom-user-daily.yml")); print("valid")'`

Expected: `valid`.

- [ ] **Step 4: Perform browser verification**

Open the local dashboard, navigate across all five pages, use the sync control once, and confirm that normal navigation no longer produces a database connection warning.

- [ ] **Step 5: Review the diff for scope and secret safety**

Run: `git diff --check && git diff -- dashboard/app.py dashboard/views.py personalization/repository.py tests .env.example README.md docs/superpowers`

Expected: no whitespace errors, no secret values, and no changes to GitHub delivery logic.
