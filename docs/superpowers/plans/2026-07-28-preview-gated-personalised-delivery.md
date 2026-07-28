# Preview-gated Personalised Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add DeepSeek-backed, editable research-profile recommendations and ensure a user only receives automatic reports after a reviewed preview explicitly enables the next future schedule.

**Architecture:** The local Streamlit dashboard collects three mandatory facts, then calls a focused recommender that returns a validated `ResearchProfileInput` plus a default `ScheduleInput`. Saving the reviewed recommendation persists a disabled schedule and queues an email-free manual preview. A repository activation method is the sole path that enables a schedule after `preview_ready`; the existing scheduled GitHub Actions runner then delivers the next automatic report through the existing `main.py` generation, PDF, and SMTP functions.

**Tech Stack:** Python 3.11, Streamlit, sqlite3/libsql (Turso), OpenAI-compatible DeepSeek client already used by `main.py`, GitHub Actions, unittest.

## Global Constraints

- Keep all existing fixed-subject workflows unchanged.
- The dashboard UI remains Chinese; internal identifiers remain stable English values.
- Profile defaults must inherit `main.resolve_llm_config()` and must not hard-code OpenAI.
- A manual preview must never send email.
- Schedule activation must set `next_run_at` strictly later than activation time.
- Do not add PostgreSQL, Redis, Celery, Docker, or a new external service.
- Never display or log secret values.

---

## File structure

- Create `personalization/recommender.py`: OpenAI-compatible structured recommendation client and strict response validation.
- Modify `personalization/models.py`: recommendation request/result data contracts.
- Modify `personalization/repository.py`: disabled schedule persistence, post-preview activation, and delivery schedule state.
- Modify `personalization/github.py`, `custom_user_daily.py`, and `.github/workflows/custom-user-daily.yml`: remove the manual preview email route.
- Modify `dashboard/views.py`: mandatory facts → recommendation review → preview → schedule activation UX.
- Modify `README.md` and tests under `tests/`.

## Task 1: Define recommendation contracts

**Files:**
- Modify: `personalization/models.py`
- Modify: `tests/test_personalization_models.py`

**Interfaces:**
- Produces `RecommendationRequest(display_name: str, email: str, research_topic: str)`.
- Produces `ProfileRecommendation(profile: ResearchProfileInput, schedule: ScheduleInput, rationale: str, uncertainty: str)`.

- [ ] **Step 1: Write failing contract tests**

```python
def test_recommendation_request_requires_the_three_operator_inputs(self):
    with self.assertRaisesRegex(ValueError, "research_topic is required"):
        RecommendationRequest.from_form("张三", "reader@example.com", "")


def test_recommendation_result_uses_a_disabled_schedule(self):
    result = ProfileRecommendation(
        profile=valid_profile(),
        schedule=ScheduleInput.from_form("daily", None, "Asia/Shanghai", "07:30", False),
        rationale="课题聚焦固态电池界面。",
        uncertainty="未指定期刊，因此使用基础学科期刊池。",
    )
    self.assertFalse(result.schedule.enabled)
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `python -m unittest tests.test_personalization_models.PersonalizationModelTests -v`

Expected: FAIL because `RecommendationRequest` and `ProfileRecommendation` do not exist.

- [ ] **Step 3: Add immutable contracts with explicit validation**

```python
@dataclass(frozen=True)
class RecommendationRequest:
    display_name: str
    email: str
    research_topic: str

    @classmethod
    def from_form(cls, display_name: str, email: str, research_topic: str) -> "RecommendationRequest":
        user = UserInput.from_form(display_name, email, "active")
        topic = research_topic.strip()
        if not topic:
            raise ValueError("research_topic is required")
        return cls(user.display_name, user.email, topic)


@dataclass(frozen=True)
class ProfileRecommendation:
    profile: ResearchProfileInput
    schedule: ScheduleInput
    rationale: str
    uncertainty: str
```

Require `ProfileRecommendation.schedule.enabled` to be `False`, so an unapproved profile cannot enter the automatic runner.

- [ ] **Step 4: Run the model suite**

Run: `python -m unittest tests.test_personalization_models -v`

Expected: PASS, including all existing profile and schedule validation tests.

- [ ] **Step 5: Record the verification checkpoint**

Do not commit unless the user explicitly authorizes a commit. Record the focused test command and result in the final implementation handoff.

## Task 2: Implement a DeepSeek-compatible, allowlisted recommender

**Files:**
- Create: `personalization/recommender.py`
- Create: `tests/test_personalization_recommender.py`

**Interfaces:**
- Consumes `RecommendationRequest` and `main.resolve_llm_config()`.
- Produces `recommend_profile(request: RecommendationRequest, request_json: Callable[[str, str], dict[str, object]] | None = None) -> ProfileRecommendation`.
- Raises `RecommendationError` for missing credentials, malformed model output, or disallowed selections.

- [ ] **Step 1: Write failing recommender tests with a fake model response**

```python
def test_recommender_uses_the_configured_provider_and_returns_editable_defaults(self):
    response = {
        "base_profile": "chemistry",
        "include_keywords": ["solid electrolyte", "SEI"],
        "exclude_keywords": ["editorial"],
        "source_ids": ["arxiv", "pubmed", "crossref"],
        "journal_ids": ["1755-4330"],
        "content_preferences": ["mechanism", "methodology"],
        "max_items": 15,
        "output_formats": ["docx", "pdf"],
        "frequency": "daily",
        "weekday": None,
        "timezone": "Asia/Shanghai",
        "local_send_time": "07:30",
        "rationale": "课题强调固态电池界面与离子传导。",
        "uncertainty": "未给出目标期刊层级。",
    }
    recommendation = recommend_profile(valid_request(), request_json=lambda *_: response)
    self.assertEqual(recommendation.profile.llm_provider, "deepseek")
    self.assertFalse(recommendation.schedule.enabled)


def test_recommender_rejects_a_journal_outside_the_selected_profile(self):
    with self.assertRaisesRegex(RecommendationError, "journal_ids"):
        recommend_profile(valid_request(), request_json=lambda *_: invalid_journal_response())
```

- [ ] **Step 2: Run the recommender tests and verify they fail**

Run: `python -m unittest tests.test_personalization_recommender -v`

Expected: FAIL because the recommender module is missing.

- [ ] **Step 3: Implement one structured model call with strict local validation**

```python
class RecommendationError(RuntimeError):
    pass


def allowed_journal_ids(base_profile: str) -> set[str]:
    return {
        issn
        for journal in main.resolve_profile(base_profile)["crossref_journals"]
        for issn in journal["issns"]
    }
```

Build one prompt from the mandatory research topic plus the five supported profile IDs, four source IDs, four content preferences, and selected-profile ISSNs. Ask the model to analyse deeply internally but return only one JSON object with selections, a short Chinese rationale, and a short uncertainty note; do not request or show chain-of-thought.

When `request_json` is absent, use `main.resolve_llm_config()`, the existing `main.OpenAI` client convention, `main.extract_response_text()`, and `main.parse_json_object()`. Construct the result with the resolved provider/model. Reject any response not accepted by `ResearchProfileInput.from_form`, a `ScheduleInput` built with `enabled=False`, and the selected profile's ISSN allowlist.

- [ ] **Step 4: Run recommender and model tests**

Run: `python -m unittest tests.test_personalization_recommender tests.test_personalization_models -v`

Expected: PASS without a live model key; the fake callback exercises model-output paths.

- [ ] **Step 5: Record the verification checkpoint**

Do not commit unless the user explicitly authorizes a commit. Record the focused test command and result in the final implementation handoff.

## Task 3: Gate schedules on a successful preview

**Files:**
- Modify: `personalization/repository.py`
- Modify: `tests/test_personalization_repository.py`

**Interfaces:**
- Produces `activate_schedule_after_preview(user_id: str, delivery_id: str, now_utc: datetime) -> ScheduleRecord`.
- Consumes a manual delivery in `preview_ready` state for the same user.
- Extends recent delivery dictionaries with `user_id` and `schedule_enabled`.

- [ ] **Step 1: Write failing repository tests**

```python
def test_disabled_schedule_is_not_due_until_approved_preview_enables_it(self):
    user_id, delivery_id = self.create_user_and_mark_preview_ready(schedule_enabled=False)
    self.assertEqual(self.repository.list_due_schedules(self.now), [])

    schedule = self.repository.activate_schedule_after_preview(user_id, delivery_id, self.now)

    self.assertTrue(schedule.enabled)
    self.assertGreater(schedule.next_run_at, self.now)


def test_activation_rejects_a_preview_for_another_user_or_non_preview_state(self):
    with self.assertRaisesRegex(ValueError, "preview_ready"):
        self.repository.activate_schedule_after_preview(other_user_id, delivery_id, self.now)
```

- [ ] **Step 2: Run the repository tests and verify they fail**

Run: `python -m unittest tests.test_personalization_repository -v`

Expected: FAIL because `activate_schedule_after_preview` does not exist.

- [ ] **Step 3: Implement atomic schedule activation**

Within one repository transaction, require a same-user manual `preview_ready` delivery. Rebuild its schedule from stored frequency, weekday, timezone, and local time; then update `enabled = 1` and `next_run_at = compute_next_run(enabled_schedule, now_utc)`. Append a `schedule_activated` event to the preview's report run; do not mutate the preview delivery and do not invoke email code.

Create a new user from a reviewed profile with active user status and a disabled `ScheduleInput`. Existing active users with enabled schedules retain their current behaviour. Extend `list_recent_deliveries()` with joined `user_id` and `schedule_enabled` values for UI logic.

- [ ] **Step 4: Run repository and runner suites**

Run: `python -m unittest tests.test_personalization_repository tests.test_custom_runner -v`

Expected: PASS; no due schedule exists before activation, and activation itself sends no email.

- [ ] **Step 5: Record the verification checkpoint**

Do not commit unless the user explicitly authorizes a commit. Record the focused test command and result in the final implementation handoff.

## Task 4: Remove the manual-preview email path

**Files:**
- Modify: `personalization/github.py`
- Modify: `custom_user_daily.py`
- Modify: `personalization/custom_runner.py`
- Modify: `.github/workflows/custom-user-daily.yml`
- Modify: `tests/test_github_dispatch.py`
- Modify: `tests/test_custom_runner.py`

**Interfaces:**
- `DispatchCommand` contains only `"preview"` and `"retry"`.
- `custom_user_daily.py` accepts only `scan`, `preview`, `artifact-metadata`, and `retry`.
- `generate_preview()` remains email-free; automatic scan remains the only custom email sender.

- [ ] **Step 1: Replace manual-send tests with boundary tests**

```python
def test_preview_never_calls_the_mailer(self):
    exit_code = generate_preview(repository, delivery_id, fake_services)
    self.assertEqual(exit_code, 0)
    self.assertEqual(fake_services.mailer_calls, [])


def test_dashboard_dispatch_contract_rejects_deliver(self):
    with self.assertRaises(ValueError):
        build_dispatch_request(settings, "deliver", "dlv_123")
```

- [ ] **Step 2: Run focused tests and verify they fail**

Run: `python -m unittest tests.test_custom_runner tests.test_github_dispatch -v`

Expected: FAIL because `deliver` remains an accepted dispatch command or existing tests assert the old behaviour.

- [ ] **Step 3: Remove the old delivery command end-to-end**

Remove `deliver`, `prepare-delivery`, and `complete-delivery` CLI branches; remove `send_confirmed_preview()` and the `deliver` job. Simplify manual retry so it only redispatches preview generation. Keep `scan` unchanged: it is the only route that sends a custom user's email and it still calls `main.send_report_email()` through `default_services()`.

Retain artifact upload and metadata because the operator still reviews the generated preview PDF.

- [ ] **Step 4: Run focused tests and parse the workflow**

Run: `python -m unittest tests.test_custom_runner tests.test_github_dispatch -v`

Run: `ruby -e 'require "yaml"; ARGV.each { |path| YAML.load_file(path) }; puts "workflow YAML OK"' .github/workflows/custom-user-daily.yml`

Expected: PASS; no dashboard dispatch can request a manual email send.

- [ ] **Step 5: Record the verification checkpoint**

Do not commit unless the user explicitly authorizes a commit. Record the focused test command and result in the final implementation handoff.

## Task 5: Replace dashboard onboarding and approval UI

**Files:**
- Modify: `dashboard/views.py`
- Modify: `tests/test_dashboard_smoke.py`

**Interfaces:**
- Consumes `RecommendationRequest`, `recommend_profile()`, `ProfileRecommendation`, `create_user_with_profile()`, `create_manual_preview()`, and `activate_schedule_after_preview()`.
- Produces a Streamlit onboarding flow in `render_users()` and a preview approval action in `render_reports()`.

- [ ] **Step 1: Write failing dashboard smoke tests**

```python
def test_user_page_exposes_mandatory_and_recommended_stages(self):
    app = self.local_dashboard_app()
    app.sidebar.radio[0].set_value("用户画像").run()
    rendered = " ".join(element.value for element in app.markdown)
    self.assertIn("必须填写", rendered)
    self.assertIn("生成建议", rendered)


def test_preview_ready_copy_never_offers_manual_email_send(self):
    rendered = render_reports_with_preview_ready_and_disabled_schedule()
    self.assertIn("启用固定频率计划", rendered)
    self.assertNotIn("确认并发送", rendered)
```

- [ ] **Step 2: Run dashboard smoke tests and verify they fail**

Run: `python -m unittest tests.test_dashboard_smoke -v`

Expected: FAIL because the current page has one form and a “确认并发送” button.

- [ ] **Step 3: Implement the two-stage Chinese onboarding flow**

In `dashboard/views.py`, replace `_profile_form()` with:

1. **必须填写**: user name, recipient email, and research topic; **生成建议** validates and calls `recommend_profile()`.
2. **可修改的系统建议**: populate base profile, keywords, source IDs, profile-limited ISSNs, preferences, item limit, formats, provider/model, and default schedule from `ProfileRecommendation` in `st.session_state`.
3. **保存并生成预览**: validate edited controls, create an active user with a disabled schedule, create one manual preview delivery, and dispatch only `preview`.

Clear onboarding session state only after the profile is stored and the preview queue is created. Preserve mandatory input and recommended values after model or validation errors.

In `render_reports()`, retain the artifact link but replace `确认并发送` and queued-send controls with **启用固定频率计划** only when `preview_ready` has `schedule_enabled == false`. Call `activate_schedule_after_preview()` directly and show the Chinese local next-send time; do not call `dispatch_command()` for activation. Hide duplicate activation controls for already-enabled schedules. Manual retry remains preview regeneration only.

In `render_users()`, display an active user with a disabled schedule as **等待预览确认**, rather than implying automatic email is active.

- [ ] **Step 4: Run dashboard tests and browser checks**

Run: `python -m unittest tests.test_dashboard_smoke -v`

Run: `streamlit run dashboard/app.py`

Verify: Chinese mandatory/optional sections; a DeepSeek-default recommendation; editable suggestions; preview queue copy says no email; preview approval enables a plan; no “确认并发送” control; a 375px viewport has no horizontal overflow.

- [ ] **Step 5: Record the verification checkpoint**

Do not commit unless the user explicitly authorizes a commit. Record the focused test command and result in the final implementation handoff.

## Task 6: Document and run full regression

**Files:**
- Modify: `README.md`
- Modify: `.env.example` only if it lacks a non-secret note that the dashboard provider key is also used for recommendations.
- Modify: `docs/superpowers/specs/2026-07-28-preview-gated-personalised-delivery-design.md` only if implementation reveals a factual difference.

**Interfaces:**
- Documents the actual user journey and required non-secret environment variable names.

- [ ] **Step 1: Add a focused README section**

Document this exact sequence:

```text
必填信息 → 大模型建议（可修改） → 生成预览（不发邮件）
→ 启用计划 → 下一次计划时间开始自动发送
```

State that the dashboard needs the same configured provider credentials as the report runner and that a missing model key prevents recommendation rather than silently falling back.

- [ ] **Step 2: Run all project checks**

Run: `python -m unittest discover -s tests -v`

Run: `python -m compileall -q dashboard personalization`

Run: `ruby -e 'require "yaml"; ARGV.each { |path| YAML.load_file(path) }; puts "workflow YAML OK"' .github/workflows/*.yml`

Run: `git diff --check`

Expected: all tests pass, all workflow files parse, and there are no whitespace errors.

- [ ] **Step 3: Record final verification**

Do not commit unless the user explicitly authorizes a commit. Record the full test, compilation, workflow parsing, and whitespace-check results in the final implementation handoff.

## Coverage self-review

- Mandatory versus optional user data: Tasks 1, 2, and 5.
- DeepSeek-backed, editable recommendations: Tasks 1, 2, and 5.
- Preview before any email: Tasks 3, 4, and 5.
- Confirmed preview enables only the next future schedule: Tasks 3 and 5.
- Existing report/PDF/SMTP and fixed-subject workflows are reused and preserved: Tasks 3, 4, and 6.
- Failure, idempotency, and UI safety: Tasks 2 through 5.
