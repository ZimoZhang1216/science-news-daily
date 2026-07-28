# Personal Research Daily Admin Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Streamlit operations dashboard and a Turso-backed custom-user delivery path that produces personalised research daily reports through GitHub Actions, without changing the behaviour of the existing fixed-profile reports.

**Architecture:** Keep `main.py` as the source of truth for retrieval, ranking, AI summaries, DOCX, PDF and SMTP. Extract a small callable report-generation API from its current CLI body, then add a `personalization/` package for validated user-profile data, Turso/SQLite persistence, user-scoped history, scheduling, and delivery state transitions. A new GitHub Actions workflow runs custom tasks; the local Streamlit app only manages state and creates repository-dispatch commands.

**Tech Stack:** Python 3.11, existing `requests`/`python-docx`/OpenAI SDK, Streamlit, `libsql` Python client for remote Turso, built-in `sqlite3` for tests and local development, GitHub Actions, GitHub repository dispatch, LibreOffice.

## Global Constraints

- Preserve the current `python main.py --profile <profile>` contract and all existing 11 workflow files exactly as they behave today.
- Keep the dashboard local-only, bound to `127.0.0.1`; do not build customer login, payment, public deployment, Docker, Redis, Celery or PostgreSQL.
- Store every secret only in local environment variables or GitHub Actions Secrets; never write or display a secret value.
- The custom path must require complete AI summaries and a successful PDF before it can send a normal report email.
- Automatic delivery is at most once per user local report date and channel; manual preview never sends, and manual confirmation sends the previously generated PDF without re-fetching or re-summarising.
- Use UTC in persistence and convert `Schedule.timezone` with `zoneinfo.ZoneInfo` when calculating a user’s local report date and next run.
- Keep Python additions typed and use `unittest`, matching the existing test suite; external API, SMTP, PDF and GitHub calls are injected at the boundary and not performed by unit tests.
- The existing project policy prohibits automatic commits. Do not commit, push, switch branches, or edit the source worktree without a new explicit user instruction.

---

## File Structure

| Path | Responsibility |
|---|---|
| `requirements.txt` | Adds dashboard and remote Turso runtime dependencies. |
| `.env.example` | Documents blank dashboard/Turso/dispatch variable names without credential values. |
| `personalization/__init__.py` | Declares the custom-delivery package. |
| `personalization/models.py` | Validated dataclasses and status literals for users, research profiles, schedules, runs and deliveries. |
| `personalization/profile.py` | Converts a stored user profile into a safe effective copy of an existing `REPORT_PROFILES` profile and applies user include/exclude rules. |
| `personalization/schema.sql` | Idempotent SQLite/libSQL DDL, indexes and constraints for the dashboard state. |
| `personalization/repository.py` | Local SQLite and remote Turso connector plus all state transitions, history lookup and source metrics queries. |
| `personalization/github.py` | Builds and submits the narrow repository-dispatch request used by the local dashboard. |
| `personalization/custom_runner.py` | Custom workflow commands: due-schedule scan, preview generation, artifact metadata update, PDF delivery, retries and state/event recording. |
| `main.py` | Exposes a callable generation result while retaining the existing CLI; supports recipient override only for the custom delivery path. |
| `custom_user_daily.py` | Thin CLI adapter for `custom_runner.py`, designed for GitHub Actions steps. |
| `dashboard/app.py` | Streamlit entry point, local configuration checks, navigation and forms. |
| `dashboard/views.py` | Testable dashboard page renderers for Operations, Users, Reports, Sources and Settings. |
| `dashboard/style.css` | The approved white/cool-gray, navy and teal operations UI treatment. |
| `.github/workflows/custom-user-daily.yml` | Isolated schedule/dispatch workflow for custom reports and artifacts. |
| `tests/test_personalization_models.py` | Pure validation and effective-profile behavior tests. |
| `tests/test_personalization_repository.py` | Real temporary SQLite schema, versioning, history and idempotency tests. |
| `tests/test_custom_runner.py` | Runner state transitions using injected report/PDF/SMTP boundary fakes. |
| `tests/test_github_dispatch.py` | Exact repository-dispatch payload construction tests. |
| `tests/test_dashboard_smoke.py` | Streamlit application smoke and missing-configuration behavior tests. |
| `README.md` | Adds local dashboard setup, Turso/GitHub Secrets setup and safe operating instructions. |

## Interfaces

The following names are the contracts between tasks. Do not rename a later use without updating its producer and its tests.

```text
# personalization/models.py
@dataclass(frozen=True)
class ResearchProfileInput:
    base_profile: str
    research_topic: str
    include_keywords: tuple[str, ...]
    exclude_keywords: tuple[str, ...]
    source_ids: tuple[str, ...]
    journal_ids: tuple[str, ...]
    content_preferences: tuple[str, ...]
    max_items: int
    llm_provider: str
    llm_model: str
    output_formats: tuple[str, ...]

@dataclass(frozen=True)
class ScheduleInput:
    frequency: Literal["daily", "weekdays", "weekly"]
    weekday: int | None
    timezone: str
    local_send_time: time
    enabled: bool

@dataclass(frozen=True)
class DeliveryClaim:
    delivery_id: str
    report_run_id: str
    user_id: str
    email: str
    report_date: date
    options: main.ReportGenerationOptions
    research_profile: ResearchProfileInput
    effective_profile: dict[str, Any]
    created: bool

# personalization/profile.py
compose_effective_profile(profile: ResearchProfileInput, user_id: str) -> dict[str, Any]
item_matches_research_profile(item: main.NewsItem, profile: ResearchProfileInput) -> bool

# personalization/repository.py
PersonalizationRepository.initialize() -> None
PersonalizationRepository.create_user_with_profile(user: UserInput, profile: ResearchProfileInput, schedule: ScheduleInput) -> str
PersonalizationRepository.save_profile_version(user_id: str, profile: ResearchProfileInput) -> int
PersonalizationRepository.list_due_schedules(now_utc: datetime) -> list[DueSchedule]
PersonalizationRepository.enqueue_automatic_delivery(due: DueSchedule) -> DeliveryClaim
PersonalizationRepository.create_manual_preview(user_id: str, report_date: date) -> DeliveryClaim
PersonalizationRepository.claim_delivery(delivery_id: str) -> DeliveryClaim | None
PersonalizationRepository.mark_preview_ready(delivery_id: str, run_id: str, artifact_name: str, github_run_id: str) -> None
PersonalizationRepository.queue_preview_delivery(delivery_id: str) -> DeliveryClaim | None
PersonalizationRepository.claim_queued_preview_delivery(delivery_id: str) -> DeliveryClaim | None
PersonalizationRepository.retry_delivery(delivery_id: str) -> Literal["preview", "deliver"] | None
PersonalizationRepository.mark_sent(delivery_id: str) -> None
PersonalizationRepository.mark_retryable_failure(delivery_id: str, error_summary: str) -> None
PersonalizationRepository.history_for_user(user_id: str, report_date: date, lookback_days: int) -> dict[str, set[str]]
PersonalizationRepository.record_report_items(run_id: str, user_id: str, report_date: date, profile: dict[str, Any], items: list[main.NewsItem]) -> None

# personalization/custom_runner.py
run_due_deliveries(repository: PersonalizationRepository, now_utc: datetime, services: RunnerServices) -> int
generate_preview(repository: PersonalizationRepository, delivery_id: str, services: RunnerServices) -> int
send_confirmed_preview(repository: PersonalizationRepository, delivery_id: str, pdf_path: Path, services: RunnerServices) -> int

# personalization/github.py
dispatch_command(settings: DispatchSettings, command: Literal["preview", "deliver", "retry"], delivery_id: str) -> None
```

### Task 1: Add safe runtime configuration and validated domain inputs

**Files:**
- Modify: `requirements.txt`
- Modify: `.env.example`
- Create: `personalization/__init__.py`
- Create: `personalization/models.py`
- Test: `tests/test_personalization_models.py`

**Consumes:** Existing `main.REPORT_PROFILES` keys and Python standard-library `zoneinfo`.

**Produces:** `ResearchProfileInput`, `ScheduleInput`, `UserInput`, immutable stored-record dataclasses, `validate_email()`, `parse_keyword_list()`, and `validate_timezone()`.

- [ ] **Step 1: Write the failing validation tests**

```python
class PersonalizationModelTests(unittest.TestCase):
    def test_profile_input_normalizes_keywords_and_rejects_unknown_base_profile(self) -> None:
        profile = ResearchProfileInput.from_form(
            base_profile="chemistry",
            research_topic="Lithium metal batteries",
            include_keywords="SEI; solid electrolyte, SEI",
            exclude_keywords="review",
            source_ids=("arxiv", "pubmed"),
            journal_ids=(),
            content_preferences=("mechanism",),
            max_items=12,
            llm_provider="openai",
            llm_model="gpt-5.4-mini",
            output_formats=("docx", "pdf"),
        )
        self.assertEqual(profile.include_keywords, ("sei", "solid electrolyte"))
        with self.assertRaisesRegex(ValueError, "base_profile"):
            ResearchProfileInput.from_form(base_profile="unknown", research_topic="x", include_keywords="", exclude_keywords="", source_ids=(), journal_ids=(), content_preferences=(), max_items=12, llm_provider="openai", llm_model="gpt-5.4-mini", output_formats=("pdf",))

    def test_weekly_schedule_requires_a_weekday_and_valid_timezone(self) -> None:
        with self.assertRaisesRegex(ValueError, "weekday"):
            ScheduleInput.from_form("weekly", None, "Asia/Shanghai", "07:30", True)
        with self.assertRaisesRegex(ValueError, "timezone"):
            ScheduleInput.from_form("daily", None, "Mars/Olympus", "07:30", True)
```

- [ ] **Step 2: Run the focused test to prove it fails before implementation**

Run: `.venv/bin/python -m unittest tests.test_personalization_models -v`

Expected: FAIL because `personalization.models` does not exist.

- [ ] **Step 3: Add the minimum models and dependency declarations**

```python
# personalization/models.py
def parse_keyword_list(value: str) -> tuple[str, ...]:
    parts = (clean.casefold().strip() for clean in re.split(r"[,;\n]", value))
    return tuple(dict.fromkeys(part for part in parts if part))

def validate_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("timezone must be an IANA timezone") from exc
    return value

@dataclass(frozen=True)
class ScheduleInput:
    # from_form validates the three permitted frequencies, time and weekday.
```

Append `streamlit>=1.40.0` and `libsql>=0.1.0` to `requirements.txt`. Append only blank `TURSO_DATABASE_URL=`, `TURSO_AUTH_TOKEN=`, `PERSONAL_ADMIN_GITHUB_REPOSITORY=`, and `GITHUB_DISPATCH_TOKEN=` entries to `.env.example`; do not alter existing example values.

- [ ] **Step 4: Run focused and full existing unit tests**

Run: `.venv/bin/python -m unittest tests.test_personalization_models -v && .venv/bin/python -m unittest discover -s tests -v`

Expected: all new validation tests and all pre-existing tests pass.

- [ ] **Step 5: Inspect the diff for secrets and accidental fixed-profile changes**

Run: `git diff --check && git diff -- requirements.txt .env.example personalization/models.py tests/test_personalization_models.py`

Expected: no whitespace errors, no credential values, no changes to `main.py` or `.github/workflows/`.

### Task 2: Compose personalised profiles without mutating fixed profiles

**Files:**
- Create: `personalization/profile.py`
- Test: `tests/test_personalization_models.py`

**Consumes:** `ResearchProfileInput`, `main.resolve_profile()`, `main.NewsItem`, `main.is_profile_relevant()`.

**Produces:** `compose_effective_profile()` and `item_matches_research_profile()` used by the custom generator.

- [ ] **Step 1: Write failing behavior tests for profile composition and hard exclusions**

```python
def test_effective_profile_is_a_copy_with_a_personal_title(self) -> None:
    profile = self.make_profile(include_keywords="solid electrolyte", exclude_keywords="review")
    effective = compose_effective_profile(profile, "usr_001")
    base = main.resolve_profile("chemistry")
    self.assertEqual(effective["title"], "Lithium metal batteries 科研资讯日报")
    self.assertIn("solid electrolyte", effective["relevance_terms"])
    self.assertNotIn("solid electrolyte", base["relevance_terms"])

def test_exclude_keyword_wins_and_include_keyword_is_required_when_configured(self) -> None:
    profile = self.make_profile(include_keywords="battery", exclude_keywords="review")
    self.assertFalse(item_matches_research_profile(main.NewsItem("Battery review", "arXiv", None, "https://e.test/1"), profile))
    self.assertFalse(item_matches_research_profile(main.NewsItem("Protein folding", "arXiv", None, "https://e.test/2"), profile))
    self.assertTrue(item_matches_research_profile(main.NewsItem("Battery interface transport", "arXiv", None, "https://e.test/3"), profile))

def test_selected_sources_and_preference_change_only_the_effective_profile(self) -> None:
    profile = self.make_profile(source_ids=("pubmed",), journal_ids=("0002-7863",), content_preferences=("mechanism",))
    effective = compose_effective_profile(profile, "usr_001")
    self.assertEqual(effective["enabled_source_ids"], ("pubmed",))
    self.assertEqual([journal["source"] for journal in effective["crossref_journals"]], ["JACS"])
    self.assertIn("mechanism", effective["custom_preference_terms"])
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `.venv/bin/python -m unittest tests.test_personalization_models.PersonalizationProfileTests -v`

Expected: FAIL because `personalization.profile` and its functions do not exist.

- [ ] **Step 3: Implement copy-on-compose and independent matching**

```python
def compose_effective_profile(profile: ResearchProfileInput, user_id: str) -> dict[str, Any]:
    effective = copy.deepcopy(main.resolve_profile(profile.base_profile))
    effective["custom_user_id"] = user_id
    effective["title"] = f"{profile.research_topic} 科研资讯日报"
    effective["output_prefix"] = f"custom_{user_id}"
    effective["relevance_terms"] = list(dict.fromkeys([*effective["relevance_terms"], *profile.include_keywords]))
    effective["custom_source_ids"] = profile.source_ids
    effective["custom_journal_ids"] = profile.journal_ids
    effective["content_preferences"] = profile.content_preferences
    return effective

def item_matches_research_profile(item: main.NewsItem, profile: ResearchProfileInput) -> bool:
    haystack = f"{item.title} {item.abstract}".casefold()
    if any(term in haystack for term in profile.exclude_keywords):
        return False
    return not profile.include_keywords or any(term in haystack for term in profile.include_keywords)
```

Populate `enabled_source_ids` with the canonical UI values `arxiv`, `pubmed`, `crossref` and `rss`. Filter a copied `crossref_journals` list by an exact overlap with its existing `issns` list; an empty source/journal selection means “use all sources from the base profile.” Map the supported preferences `review`, `mechanism`, `methodology` and `experiment` to their existing English ranking terms and set `custom_preference_terms` on the effective copy. Use exact normalized term matching for one-word English terms and phrase substring matching for multi-word terms, reusing the project’s word-boundary helper if available rather than duplicating a second incompatible matcher. Do not edit `REPORT_PROFILES` in place.

- [ ] **Step 4: Run regression tests that prove fixed profiles remain unchanged**

Run: `.venv/bin/python -m unittest tests.test_personalization_models tests.test_business_management -v`

Expected: PASS; the existing business profile still contains none of the custom user’s keywords.

- [ ] **Step 5: Inspect mutation coverage**

Temporarily reason through these mutations before finishing: remove the deep copy, ignore exclusions, or change the include condition from `any` to always true. Confirm each would fail one of the tests written in Step 1; do not add a source-text assertion.

### Task 3: Implement Turso/SQLite schema, repository and user-scoped history

**Files:**
- Create: `personalization/schema.sql`
- Create: `personalization/repository.py`
- Test: `tests/test_personalization_repository.py`

**Consumes:** Model dataclasses from Task 1 and `main.history_item_payload()` from the existing generator.

**Produces:** `PersonalizationRepository`, transactional state transitions, `report_items` history retrieval and dashboard query methods.

- [ ] **Step 1: Write failing repository tests against a real temporary SQLite database**

```python
class RepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repo = PersonalizationRepository.for_sqlite(Path(self.tempdir.name) / "admin.db")
        self.repo.initialize()

    def test_profile_saves_an_immutable_new_version(self) -> None:
        user_id = self.repo.create_user_with_profile(self.user(), self.profile("battery"), self.daily_schedule())
        version_two = self.repo.save_profile_version(user_id, self.profile("solid electrolyte"))
        current = self.repo.get_current_profile(user_id)
        self.assertEqual(version_two, 2)
        self.assertEqual(current.version, 2)
        self.assertEqual(self.repo.list_profile_versions(user_id)[0].include_keywords, ("battery",))

    def test_duplicate_automatic_claim_for_same_user_local_date_returns_existing_delivery(self) -> None:
        due = self.create_due_schedule(user_id="usr_001", local_date=date(2026, 7, 28))
        first = self.repo.enqueue_automatic_delivery(due)
        second = self.repo.enqueue_automatic_delivery(due)
        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.delivery_id, second.delivery_id)
```

- [ ] **Step 2: Run the repository test to prove it fails**

Run: `.venv/bin/python -m unittest tests.test_personalization_repository -v`

Expected: FAIL because `PersonalizationRepository` does not exist.

- [ ] **Step 3: Create idempotent DDL and the backend connector**

`schema.sql` must contain these tables and indexes: `users`, `research_profiles`, `schedules`, `report_runs`, `deliveries`, `report_items`, `run_events`, and `source_metrics`. Use `TEXT` for UUID-like IDs and ISO-8601 UTC timestamps, foreign keys, `CHECK` constraints for every status enum, `UNIQUE(user_id, version)` for profile versions, `UNIQUE(idempotency_key)` for deliveries, and indexes on `schedules(next_run_at)`, `deliveries(status, updated_at)`, and `report_items(user_id, report_date)`.

```python
class PersonalizationRepository:
    @classmethod
    def from_environment(cls) -> "PersonalizationRepository":
        url = os.environ.get("TURSO_DATABASE_URL", "").strip()
        token = os.environ.get("TURSO_AUTH_TOKEN", "").strip()
        if not url or not token:
            raise RuntimeError("TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are required")
        import libsql
        return cls(libsql.connect(database=url, auth_token=token))

    @classmethod
    def for_sqlite(cls, path: Path) -> "PersonalizationRepository":
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        return cls(connection)
```

Read and execute `schema.sql` statement by statement for both connectors. Use an `INSERT` with `ON CONFLICT(idempotency_key) DO NOTHING` in a transaction for `enqueue_automatic_delivery`; never implement duplicate protection as a preceding `SELECT` alone.

- [ ] **Step 4: Implement profile versioning, schedule calculation, state events and history**

```python
def history_for_user(self, user_id: str, report_date: date, lookback_days: int) -> dict[str, set[str]]:
    cutoff = (report_date - timedelta(days=lookback_days)).isoformat()
    rows = self._fetchall(
        "SELECT identity_keys_json, title_key, topic_key FROM report_items "
        "WHERE user_id = ? AND report_date >= ? AND report_date < ?",
        (user_id, cutoff, report_date.isoformat()),
    )
    history = {"identity_keys": set(), "title_keys": set(), "topic_keys": set()}
    for row in rows:
        history["identity_keys"].update(json.loads(row["identity_keys_json"]))
        if row["title_key"]:
            history["title_keys"].add(row["title_key"])
        if row["topic_key"]:
            history["topic_keys"].add(row["topic_key"])
    return history
```

`save_profile_version()` must atomically mark the previous version non-current and insert the next integer version. `queue_preview_delivery()` may transition only `preview_ready → queued`; every other current state returns `None` and writes no new delivery. Every successful or rejected transition writes one `run_events` row with a redacted message.

- [ ] **Step 5: Run repository tests and the full suite**

Run: `.venv/bin/python -m unittest tests.test_personalization_repository -v && .venv/bin/python -m unittest discover -s tests -v`

Expected: PASS, including a test that records a prior DOI/title/topic and verifies the history mapping contains the expected literal fingerprints.

- [ ] **Step 6: Verify schema portability without remote credentials**

Run: `.venv/bin/python -c 'from personalization.repository import PersonalizationRepository; import tempfile; from pathlib import Path; d=tempfile.TemporaryDirectory(); r=PersonalizationRepository.for_sqlite(Path(d.name)/"schema.db"); r.initialize(); print("schema-ready")'`

Expected: `schema-ready`; no Turso token is read or printed.

### Task 4: Extract a reusable report-generation boundary from `main.py`

**Files:**
- Modify: `main.py`
- Test: `tests/test_personalization_models.py`
- Test: `tests/test_business_management.py`

**Consumes:** Existing `collect_items()`, `prepare_items()`, `generate_ai_summaries()`, `apply_ai_scientific_notation()`, `create_document()`, `create_failure_report()`, and `send_report_email()`.

**Produces:** `ReportGenerationOptions`, `ReportGenerationResult`, `generate_report()` and a safe `recipient_override` parameter used only by custom deliveries.

- [ ] **Step 1: Write focused failing API tests with no network calls**

```python
def test_generate_report_applies_user_filter_after_existing_collection(self) -> None:
    item = main.NewsItem("Battery interface transport", "arXiv", datetime(2026, 7, 28, tzinfo=timezone.utc), "https://e.test/b")
    options = main.ReportGenerationOptions(days=1, max_items=10, min_items=1, source_limit=10, max_ai_items=10, llm_provider="openai", model="", report_date=date(2026, 7, 28), output_dir=Path(self.tempdir.name), require_ai=False)
    with patch.object(main, "collect_items", return_value=([item], [main.SourceStatus("arXiv", True, 1)])), patch.object(main, "generate_ai_summaries", return_value=main.fallback_report_payload([item], self.profile)), patch.object(main, "create_document", return_value=Path(self.tempdir.name) / "report.docx"):
        result = main.generate_report(options, self.profile, item_filter=lambda candidate: "battery" in candidate.title.casefold())
    self.assertEqual(result.selected_count, 1)
    self.assertEqual(result.output_path.name, "report.docx")

def test_send_report_email_uses_explicit_custom_recipient_without_profile_environment_fallback(self) -> None:
    pdf_path = Path(self.tempdir.name) / "preview.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    smtp = CapturingSmtp()
    with patch.dict(os.environ, {"EMAIL_ENABLED": "true", "SMTP_HOST": "smtp.test", "SMTP_USERNAME": "sender@test", "SMTP_PASSWORD": "x", "SMTP_FROM": "sender@test", "SMTP_SECURITY": "ssl", "REPORT_EMAIL_TO": "wrong@test"}, clear=True), patch.object(main.smtplib, "SMTP_SSL", return_value=smtp):
        sent = main.send_report_email(pdf_path, date(2026, 7, 28), self.profile, ai_generated=True, recipient_override=["client@test"])
    self.assertTrue(sent)
    self.assertEqual(smtp.messages[0]["To"], "client@test")
```

- [ ] **Step 2: Run the focused test to prove the new public boundary is absent**

Run: `.venv/bin/python -m unittest tests.test_personalization_models.ReportGenerationApiTests -v`

Expected: FAIL because `ReportGenerationOptions` and `generate_report` do not exist.

- [ ] **Step 3: Implement a narrow reusable generation function and retain the CLI wrapper**

```python
@dataclass(frozen=True)
class ReportGenerationOptions:
    days: int
    max_items: int
    min_items: int
    source_limit: int
    max_ai_items: int
    llm_provider: str
    model: str
    report_date: date
    output_dir: Path
    require_ai: bool

@dataclass
class ReportGenerationResult:
    output_path: Path
    selected_items: list[NewsItem]
    source_statuses: list[SourceStatus]
    report_payload: dict[str, Any]
    collected_count: int
    selected_count: int
    ai_generated: bool
    failure_exit_code: int | None

def generate_report(options: ReportGenerationOptions, profile: dict[str, Any], history: dict[str, set[str]] | None = None, item_filter: Callable[[NewsItem], bool] | None = None) -> ReportGenerationResult:
    now = datetime.now(timezone.utc)
    from network_check import run_network_checks
    diagnostics = run_network_checks(logger=LOGGER)
    collected, statuses = collect_items(SimpleNamespace(source_limit=options.source_limit), now - timedelta(days=options.days), now, profile)
    filtered = [item for item in collected if item_filter is None or item_filter(item)]
    prepared = prepare_items(filtered, options.max_items, now, profile, history=history, min_items=options.min_items)
    ensure_item_ids(prepared)
    if not prepared:
        output_path = create_failure_report(report_date=options.report_date, output_dir=options.output_dir, profile=profile, diagnostics=diagnostics, source_statuses=statuses, reason="抓取和过滤后没有可写入日报的资讯。", collected_count=len(collected), prepared_count=0)
        return ReportGenerationResult(output_path, [], statuses, {}, len(collected), 0, False, 1)
    payload = generate_ai_summaries(prepared, options.model, options.max_ai_items, profile, provider_override=options.llm_provider)
    if options.require_ai and not payload.get("ai_generated"):
        return ReportGenerationResult(Path(), prepared, statuses, payload, len(collected), len(prepared), False, 4)
    payload["notation_ai_generated"] = apply_ai_scientific_notation(prepared, payload, options.model, profile, enabled=True, provider_override=options.llm_provider)
    output_path = create_document(prepared, payload, options.report_date, options.output_dir, profile, diagnostics=diagnostics, source_statuses=statuses)
    return ReportGenerationResult(output_path, prepared, statuses, payload, len(collected), len(prepared), bool(payload.get("ai_generated")), None)
```

Extend `collect_items()` so `profile.get("enabled_source_ids")` skips disabled top-level fetchers, while no value preserves the existing all-source behavior. The copied `crossref_journals` and RSS entries from Task 2 then limit journal/RSS fetches. Extend `rank_item()` to add a bounded bonus for terms in `profile.get("custom_preference_terms", ())`, preserving every existing fixed-profile score when that key is absent. Add optional `provider_override` arguments to `resolve_llm_config()`, `generate_ai_summaries()` and `apply_ai_scientific_notation()`; `ReportGenerationOptions.llm_provider` supplies this only for custom tasks, while existing CLI calls continue to use `LLM_PROVIDER`. Apply `item_filter` after `collect_items()` and before `prepare_items()`. Keep the existing CLI’s validation, local JSON history loading/saving, return codes and email call in `main()`; it should construct `ReportGenerationOptions`, call `generate_report()`, then preserve its existing return behavior. Extend `send_report_email()` with `recipient_override: list[str] | None = None`; when supplied, make it the sole recipient option and never read profile/default recipient environment variables.

- [ ] **Step 4: Run fixed-profile and new API regressions**

Run: `.venv/bin/python -m unittest tests.test_personalization_models.ReportGenerationApiTests tests.test_business_management -v && .venv/bin/python -m unittest discover -s tests -v`

Expected: PASS; no live data source, SMTP server or model is contacted.

- [ ] **Step 5: Perform a local non-email CLI smoke test**

Run: `.venv/bin/python main.py --profile chemistry --days 1 --no-openai --no-email --output-dir ./output-plan-smoke`

Expected: a DOCX or existing structured failure report is created, and the command follows its existing documented exit behavior. Remove only the explicit generated `./output-plan-smoke` directory after inspection; do not touch any existing output directory.

### Task 5: Implement custom preview generation and automatic due scheduling

**Files:**
- Create: `personalization/custom_runner.py`
- Create: `custom_user_daily.py`
- Test: `tests/test_custom_runner.py`

**Consumes:** Task 2 effective profiles, Task 3 repository, Task 4 generation boundary, and current history fingerprint helpers in `main.py`.

**Produces:** A runner that creates previews and automatic reports with correct history, state records and deterministic artifact metadata, but does not deliver preview emails.

- [ ] **Step 1: Write failing runner tests around observable side effects**

```python
def test_preview_generates_a_report_marks_preview_ready_and_never_calls_mailer(self) -> None:
    claim = self.repo.create_manual_preview(self.user_id, date(2026, 7, 28))
    services = RunnerServices(generator=self.successful_generator, pdf_converter=self.successful_pdf, mailer=self.fail_if_called, github_run_id="123")
    exit_code = generate_preview(self.repo, claim.delivery_id, services)
    delivery = self.repo.get_delivery(claim.delivery_id)
    self.assertEqual(exit_code, 0)
    self.assertEqual(delivery.status, "preview_ready")
    self.assertEqual(delivery.artifact_name, f"custom-report-{delivery.report_run_id}")

def test_automatic_due_delivery_uses_user_history_and_stops_after_two_recoverable_failures(self) -> None:
    user_id = self.repo.create_user_with_profile(self.user(), self.profile("battery"), self.daily_schedule_due_now())
    services = RunnerServices(generator=self.recoverably_failing_generator, pdf_converter=self.successful_pdf, mailer=self.fail_if_called, github_run_id="123")
    for _ in range(3):
        run_due_deliveries(self.repo, datetime(2026, 7, 28, 0, 0, tzinfo=timezone.utc), services)
    delivery = self.repo.list_deliveries_for_user(user_id)[0]
    self.assertEqual(delivery.status, "retryable_failed")
    self.assertEqual(delivery.attempt_count, 3)
```

- [ ] **Step 2: Run the runner test to prove it fails**

Run: `.venv/bin/python -m unittest tests.test_custom_runner -v`

Expected: FAIL because `personalization.custom_runner` does not exist.

- [ ] **Step 3: Implement explicit service injection and preview execution**

```python
@dataclass(frozen=True)
class RunnerServices:
    generator: Callable[[main.ReportGenerationOptions, dict[str, Any], dict[str, set[str]], Callable[[main.NewsItem], bool]], main.ReportGenerationResult]
    pdf_converter: Callable[[Path], Path | None]
    mailer: Callable[[Path, date, dict[str, Any], list[str]], bool]
    github_run_id: str

def generate_preview(repository: PersonalizationRepository, delivery_id: str, services: RunnerServices) -> int:
    claim = repository.claim_delivery(delivery_id)
    if claim is None:
        return 0
    generated = services.generator(claim.options, claim.effective_profile, repository.history_for_user(claim.user_id, claim.report_date, 10), lambda item: item_matches_research_profile(item, claim.research_profile))
    if generated.failure_exit_code is not None or not generated.ai_generated:
        repository.mark_retryable_failure(delivery_id, "AI summary incomplete or no reportable items")
        return 4
    pdf_path = services.pdf_converter(generated.output_path)
    if pdf_path is None:
        repository.mark_retryable_failure(delivery_id, "PDF conversion failed")
        return 3
    repository.record_report_items(claim.report_run_id, claim.user_id, claim.report_date, claim.effective_profile, generated.selected_items)
    repository.mark_preview_ready(delivery_id, claim.report_run_id, f"custom-report-{claim.report_run_id}", services.github_run_id)
    return 0
```

For automatic mode, `run_due_deliveries()` first loads newly due schedules and recoverable automatic deliveries with fewer than three attempts. It uses the same collection, AI, DOCX and PDF steps, then calls `services.mailer(pdf_path, claim.report_date, claim.effective_profile, [claim.email])` immediately. It calls `mark_sent()` only when the mailer returns `True`; it calls `mark_retryable_failure()` otherwise. The manual preview path above never invokes `mailer`. The runner must update `next_run_at` after a newly due claim using the user timezone, frequency and weekday. `retry_delivery()` must atomically select `deliver` when an artifact run ID/name already exists and `preview` when no artifact exists, then make that state visible to the dashboard before it dispatches `retry`.

- [ ] **Step 4: Add the thin workflow CLI**

```python
# custom_user_daily.py
parser.add_argument("command", choices=("scan", "preview", "prepare-delivery", "complete-delivery", "retry"))
parser.add_argument("--delivery-id", default="")
parser.add_argument("--pdf-path", default="")
# The command opens PersonalizationRepository.from_environment(), calls one runner function, then exits with its returned code.
```

For `prepare-delivery`, print only GitHub Actions output-safe lines: `delivery_id=`, `artifact_name=`, and `artifact_run_id=`. Never print email address, source abstracts, database URL or any token.

- [ ] **Step 5: Run tests and a no-credential help smoke check**

Run: `.venv/bin/python -m unittest tests.test_custom_runner -v && .venv/bin/python custom_user_daily.py --help`

Expected: all tests pass and help exits successfully without opening a database connection.

### Task 6: Implement confirmation delivery, retry bounds and dispatch client

**Files:**
- Create: `personalization/github.py`
- Modify: `personalization/custom_runner.py`
- Test: `tests/test_custom_runner.py`
- Test: `tests/test_github_dispatch.py`

**Consumes:** Preview delivery artifact metadata from Task 5 and recipient override from Task 4.

**Produces:** `send_confirmed_preview()` and `dispatch_command()`, both idempotent and safe to call repeatedly.

- [ ] **Step 1: Write failing tests for confirmation and exact dispatch contract**

```python
def test_confirmation_sends_the_existing_pdf_once_and_never_invokes_generator(self) -> None:
    delivery = self.ready_preview_delivery()
    services = RunnerServices(generator=self.fail_if_called, pdf_converter=self.fail_if_called, mailer=self.successful_mailer, github_run_id="999")
    self.assertEqual(send_confirmed_preview(self.repo, delivery.id, self.pdf_path, services), 0)
    self.assertEqual(send_confirmed_preview(self.repo, delivery.id, self.pdf_path, services), 0)
    self.assertEqual(self.sent_paths, [self.pdf_path])
    self.assertEqual(self.repo.get_delivery(delivery.id).status, "sent")

def test_dispatch_request_has_only_the_expected_command_and_delivery_id(self) -> None:
    request = build_dispatch_request(DispatchSettings("owner/repo", "token"), "preview", "dlv_123")
    self.assertEqual(request.url, "https://api.github.com/repos/owner/repo/dispatches")
    self.assertEqual(request.json, {"event_type": "personal-news-command", "client_payload": {"command": "preview", "delivery_id": "dlv_123"}})
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `.venv/bin/python -m unittest tests.test_custom_runner.CustomDeliveryTests tests.test_github_dispatch -v`

Expected: FAIL because confirmation and dispatch functions are absent.

- [ ] **Step 3: Implement delivery state machine and dispatch request construction**

```python
def send_confirmed_preview(repository: PersonalizationRepository, delivery_id: str, pdf_path: Path, services: RunnerServices) -> int:
    claim = repository.claim_queued_preview_delivery(delivery_id)
    if claim is None:
        return 0
    if not pdf_path.is_file():
        repository.mark_retryable_failure(delivery_id, "Preview PDF artifact is missing")
        return 3
    if not services.mailer(pdf_path, claim.report_date, claim.effective_profile, [claim.email]):
        repository.mark_retryable_failure(delivery_id, "SMTP delivery failed")
        return 3
    repository.mark_sent(delivery_id)
    return 0
```

Permit at most two recoverable failed attempts. On the third recoverable failure, set `retryable_failed`; never allow a `sent` delivery to return to `queued`. Implement `build_dispatch_request()` as a pure function and `dispatch_command()` with `requests.post(request.url, headers=request.headers, json=request.json, timeout=20)`, `Accept: application/vnd.github+json`, bearer token only in the header, and `response.raise_for_status()`.

- [ ] **Step 4: Run state-machine, dispatch and full unit tests**

Run: `.venv/bin/python -m unittest tests.test_custom_runner tests.test_github_dispatch -v && .venv/bin/python -m unittest discover -s tests -v`

Expected: PASS; repeat confirmation makes one mailer call, and an SMTP failure never transitions to `sent`.

- [ ] **Step 5: Review error redaction behavior**

Run: `rg -n "token|password|email|authorization" personalization tests/test_custom_runner.py tests/test_github_dispatch.py`

Expected: tests use only synthetic values; no production logger or exception persistence includes a secret or full recipient address.

### Task 7: Add an isolated custom-user GitHub Actions workflow

**Files:**
- Create: `.github/workflows/custom-user-daily.yml`
- Test: `tests/test_github_dispatch.py`

**Consumes:** `custom_user_daily.py`, Turso secrets, existing LLM/SMTP secrets and deterministic artifact metadata.

**Produces:** A 15-minute due scan and a repository-dispatch command path, without changing any existing workflow.

- [ ] **Step 1: Write a behavior test for the workflow payload parser helper**

```python
def test_command_parser_rejects_unknown_dispatch_command(self) -> None:
    with self.assertRaises(SystemExit):
        custom_user_daily.build_parser().parse_args(["not-a-command"])
```

- [ ] **Step 2: Run it and verify it fails until the CLI parser from Task 5 exists**

Run: `.venv/bin/python -m unittest tests.test_github_dispatch.CustomWorkflowCliTests -v`

Expected: FAIL before Task 5 is complete; PASS once Task 5’s parser has been implemented.

- [ ] **Step 3: Create the new workflow with isolated triggers and permissions**

```yaml
name: Custom User Research Daily
on:
  schedule:
    - cron: "*/15 * * * *"
  workflow_dispatch:
  repository_dispatch:
    types: [personal-news-command]
permissions:
  contents: read
  actions: read
concurrency:
  group: custom-user-daily-${{ github.ref }}
  cancel-in-progress: false
```

Set `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, the existing model/SMTP values, and `EMAIL_ENABLED=true` from Secrets. Install the existing requirements plus LibreOffice/Noto CJK exactly as the current email workflows do. For schedule events run `python custom_user_daily.py scan`. For a `preview` command run the preview generator and upload `output/custom/$DELIVERY_ID/` with the deterministic artifact name written by the runner. For a `deliver` command, run `prepare-delivery`, download the named artifact from its saved `artifact_run_id` with `actions/download-artifact@v4`, then run `complete-delivery --delivery-id "$DELIVERY_ID" --pdf-path "$PDF_PATH"`.

Use `if:` guards on the event command so automatic scan, preview, delivery and retry paths cannot accidentally run in the same job. For `retry`, use the runner’s printed `next_command` output to select the existing preview or delivery subpath. Set a `GITHUB_RUN_ID` environment variable for the runner and upload artifacts only when preview generation succeeds.

- [ ] **Step 4: Parse the new workflow and compare existing workflow files**

Run: `ruby -e 'require "yaml"; YAML.load_file(".github/workflows/custom-user-daily.yml"); puts "yaml-ok"' && git diff -- .github/workflows`

Expected: `yaml-ok`, and the diff names only `custom-user-daily.yml`.

- [ ] **Step 5: Validate the command contract locally without secrets**

Run: `.venv/bin/python custom_user_daily.py --help && .venv/bin/python -m unittest tests.test_github_dispatch -v`

Expected: PASS; no dispatch is issued and no GitHub Action is triggered from local verification.

### Task 8: Build the local Streamlit operations dashboard

**Files:**
- Create: `dashboard/app.py`
- Create: `dashboard/views.py`
- Create: `dashboard/style.css`
- Test: `tests/test_dashboard_smoke.py`

**Consumes:** Tasks 1–3 repository API and Task 6 `dispatch_command()`.

**Produces:** A local, operations-first dashboard that manages real profiles/schedules, starts preview/confirmation commands, and explains missing configuration without exposing values.

- [ ] **Step 1: Write a failing Streamlit smoke test for safe missing configuration**

```python
class DashboardSmokeTests(unittest.TestCase):
    def test_settings_page_reports_missing_database_configuration_without_secret_values(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            app = AppTest.from_file("dashboard/app.py")
            app.run()
        self.assertTrue(any("Turso connection is not configured" in element.value for element in app.info))
        self.assertNotIn("TURSO_AUTH_TOKEN=", " ".join(element.value for element in app.info))
```

- [ ] **Step 2: Run the dashboard smoke test and verify it fails**

Run: `.venv/bin/python -m unittest tests.test_dashboard_smoke -v`

Expected: FAIL because `dashboard/app.py` does not exist.

- [ ] **Step 3: Implement the five approved pages and dispatch actions**

```python
# dashboard/app.py
st.set_page_config(page_title="Research Daily Operations", page_icon="🧪", layout="wide")
page = st.sidebar.radio("Workspace", ["Operations", "Users", "Reports & Delivery", "Sources & Metrics", "Settings"])
repository = get_repository_or_none()
render_page(page, repository)
```

Implement each page in `dashboard/views.py`:

1. **Operations:** query today’s queued/sent/retryable counts, source health and recent events; show actionable user name, redacted email, local next-send time and status.
2. **Users:** show a table and a `st.form` that validates display name, email, topic, base profile, comma/semicolon keyword lists, source/journal multi-selects, content preferences, max items, model, output formats, timezone, frequency and optional weekly weekday. Saving creates a new profile version rather than overwriting history. Pause/resume changes `users.status` and `schedules.enabled` deliberately.
3. **Reports & Delivery:** create a manual preview, call `dispatch_command(settings, "preview", delivery_id)`, display artifact/run links for `preview_ready`, and require an explicit confirmation button before `dispatch_command(settings, "deliver", delivery_id)`. A sent item has no confirmation button. A retry button only appears for `retryable_failed`, calls `retry_delivery()`, then dispatches `dispatch_command(settings, "retry", delivery_id)`.
4. **Sources & Metrics:** read `source_metrics` and `run_events`, show source success rate, candidate/selected totals, run duration and model usage when present.
5. **Settings:** show only boolean readiness for Turso, dispatch repository/token and current local binding; no secret values or full token-derived data.

Add CSS matching the accepted concepts: a true white main surface, #F4F7FA application frame, navy text, thin blue-gray dividers, teal primary buttons, left navigation, compact metric cards, tables and status chips. Do not add a marketing hero, a bento-card wall, public login UI, warm backgrounds or decorative images.

- [ ] **Step 4: Run automated dashboard tests and start the local server**

Run: `.venv/bin/python -m unittest tests.test_dashboard_smoke -v && .venv/bin/streamlit run dashboard/app.py --server.address 127.0.0.1 --server.port 8501`

Expected: smoke test passes; the app opens only at `http://127.0.0.1:8501` and reports a clear readiness state before credentials are configured.

- [ ] **Step 5: Perform visual and interaction verification in the browser**

Open the local dashboard and verify at desktop and narrow mobile widths: left navigation remains usable, no text overlaps, tables remain readable, required form errors are visible, preview requires a confirmation click, and Settings never prints a secret. Compare against the approved operations overview, profile-editing, and preview-confirmation concepts; record any mismatch and correct it before calling the task complete.

### Task 9: Document operation, run end-to-end safe checks and protect the existing path

**Files:**
- Modify: `README.md`
- Modify: `.env.example`
- Modify: `docs/superpowers/specs/2026-07-28-personal-admin-dashboard-design.md` only if implementation reveals a confirmed interface difference
- Test: all `tests/`

**Consumes:** Completed dashboard, runner and workflow.

**Produces:** Reproducible setup steps and evidence that existing fixed-profile automation remains intact.

- [ ] **Step 1: Add precise operator documentation**

Document these commands and no secret values:

```bash
pip install -r requirements.txt
streamlit run dashboard/app.py --server.address 127.0.0.1
python -m unittest discover -s tests -v
```

Explain the one-time Turso database initialization, the GitHub Secrets required by `custom-user-daily.yml`, the local-only dashboard variables, the manual preview → confirmation flow, automatic retry limit, artifact retention limitation, and how to pause a user before editing a live profile. State that fixed subject reports and their workflows stay separate.

- [ ] **Step 2: Run the complete verification suite**

Run: `.venv/bin/python -m unittest discover -s tests -v && ruby -e 'Dir[".github/workflows/*.yml"].each { |f| YAML.load_file(f) }; puts "all-workflows-yaml-ok"'`

Expected: every unit test passes and all 12 workflow files parse.

- [ ] **Step 3: Run a controlled SQLite end-to-end simulation**

Use a temporary SQLite path and injected fake generator/PDF/mailer to execute this observable sequence: create user → create manual preview → generate preview → confirm once → send once → confirm again → no second send. Assert the final delivery is `sent`, exactly one mailer call occurred, and the matching `report_items` rows were stored.

Run: `.venv/bin/python -m unittest tests.test_custom_runner.CustomDeliveryTests.test_manual_preview_to_confirmed_send_is_idempotent -v`

Expected: PASS with no network, SMTP or model request.

- [ ] **Step 4: Check scope and security before handoff**

Run: `git diff --check && git status --short && rg -n "(OPENAI_API_KEY|DEEPSEEK_API_KEY|SMTP_PASSWORD|TURSO_AUTH_TOKEN|GITHUB_DISPATCH_TOKEN)=" --glob '!*.example' --glob '!README.md' .`

Expected: no whitespace errors and no secret assignments in tracked source, tests, docs or workflow logs. Review the status output to ensure only the planned dashboard/custom-delivery files changed; do not commit without explicit user authorization.
