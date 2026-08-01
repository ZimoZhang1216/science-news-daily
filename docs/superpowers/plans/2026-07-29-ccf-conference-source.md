# CCF Conference Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional CCF-tiered conference-paper source to personalised computer-science dailies, defaulting new profiles to A+B and allowing A, A+B, or A+B+C.

**Architecture:** Keep a versioned CCF venue catalogue in `personalization/ccf_catalogue.py`. Persist a small tier-list setting in immutable profile versions, and use DBLP's public update feed plus matching proceedings pages to construct normal `NewsItem` objects. Existing collection, relevance, history deduplication, ranking, reports, and delivery code consume those objects unchanged.

**Tech Stack:** Python 3.14, requests, feedparser, BeautifulSoup, SQLite/libsql (Turso), Streamlit, unittest.

## Global Constraints

- CCF source ID is `ccf_conferences`, available only to `computer_science` profiles.
- `ccf_conference_tiers` only accepts the non-empty ordered subset of `A`, `B`, and `C`; new and legacy profiles default to `("A", "B")`.
- New/recommended computer-science profiles opt into `ccf_conferences`; existing saved profiles do not gain a new enabled source.
- The information window filters DBLP feed update timestamps, which are labelled as DBLP indexing time rather than conference publication time.
- Network, model, SMTP, and user-email data must not be used by automated tests or logs.
- Fixed-subject dailies and non-computer-science personalised profiles must retain their existing collection path and source choices.

---

### Task 1: Versioned CCF venue catalogue and source availability

**Files:**
- Create: `personalization/ccf_catalogue.py`
- Create: `tests/test_ccf_catalogue.py`
- Modify: `main.py: ACADEMIC_SOURCE_IDS, SUPPORTED_SOURCE_IDS, available_source_ids, computer_science profile`
- Modify: `dashboard/views.py: SOURCE_LABELS`

**Interfaces:**
- Produces: `CcfConference(tier: str, abbreviation: str, dblp_path: str)`.
- Produces: `CCF_CATALOGUE_VERSION: str`, `CCF_CONFERENCES: tuple[CcfConference, ...]`, `conferences_for_tiers(tiers: Collection[str]) -> tuple[CcfConference, ...]`.
- Consumes: `main.available_source_ids("computer_science")`.

- [x] **Step 1: Write failing catalogue and availability tests**

```python
from personalization.ccf_catalogue import conferences_for_tiers

def test_catalogue_has_current_ai_and_database_a_tier_venues(self) -> None:
    venues = {venue.abbreviation for venue in conferences_for_tiers(("A",))}
    self.assertTrue({"AAAI", "NeurIPS", "SIGMOD", "VLDB"}.issubset(venues))

def test_ccf_source_is_available_only_for_computer_science(self) -> None:
    self.assertIn("ccf_conferences", main.available_source_ids("computer_science"))
    self.assertNotIn("ccf_conferences", main.available_source_ids("statistics"))
```

- [x] **Step 2: Run the focused tests to verify red**

Run: `.venv/bin/python -m unittest tests.test_ccf_catalogue -q`

Expected: import/source-availability failures because the catalogue and source ID do not exist.

- [x] **Step 3: Add the catalogue and source registration**

Define the CCF 2026 conference records used by the CCF category pages, with one canonical DBLP `/db/conf/.../` path and a display abbreviation. Include the full A/B/C catalogue, not only AI venues. Add `ccf_conferences` as an academic source, configure it for `computer_science`, and keep it absent from all other base profiles. Add the dashboard label `CCF 推荐会议（DBLP 新收录）`.

- [x] **Step 4: Run the focused tests to verify green**

Run: `.venv/bin/python -m unittest tests.test_ccf_catalogue -q`

Expected: catalogue tier filtering and profile availability pass without network access.

### Task 2: Immutable profile tier setting and additive database compatibility

**Files:**
- Modify: `personalization/models.py`
- Modify: `personalization/schema.sql`
- Modify: `personalization/repository.py`
- Modify: `personalization/profile.py`
- Modify: `tests/test_personalization_models.py`
- Modify: `tests/test_personalization_repository.py`

**Interfaces:**
- Produces: `ResearchProfileInput.ccf_conference_tiers: tuple[str, ...]`.
- Consumes: `ResearchProfileInput.from_form(..., ccf_conference_tiers: str | Sequence[str] = ("A", "B"))`.
- Produces: effective profile key `ccf_conference_tiers` for the collector.

- [x] **Step 1: Write failing validation, migration, and composition tests**

```python
profile = self.valid_profile(ccf_conference_tiers=["A", "B", "C"])
self.assertEqual(profile.ccf_conference_tiers, ("A", "B", "C"))
with self.assertRaisesRegex(ValueError, "ccf_conference_tiers"):
    self.valid_profile(ccf_conference_tiers=[])

self.assertEqual(legacy_profile.input.ccf_conference_tiers, ("A", "B"))
self.assertEqual(effective["ccf_conference_tiers"], ("A", "C"))
```

Build a legacy `research_profiles` table without `ccf_conference_tiers_json`, initialize the repository, then assert the existing record still loads and defaults to A+B.

- [x] **Step 2: Run the focused tests to verify red**

Run: `.venv/bin/python -m unittest tests.test_personalization_models tests.test_personalization_repository -q`

Expected: failures because the field, migration, and effective-profile value are absent.

- [x] **Step 3: Add validation, persistence, and replica fallback**

Add `ccf_conference_tiers_json TEXT NOT NULL DEFAULT '["A", "B"]'` to the fresh schema and an additive migration in `_migrate_scheduler_schema`. Parse legacy/stale replica rows as A+B, insert the JSON value for new versions, and pass the immutable tuple through `compose_effective_profile`. Reject blank, duplicate, unsupported, or non-canonical tier lists before database writes.

- [x] **Step 4: Run the focused tests to verify green**

Run: `.venv/bin/python -m unittest tests.test_personalization_models tests.test_personalization_repository -q`

Expected: all profile versions round-trip their tier selection, including legacy and stale-replica compatibility.

### Task 3: Bounded DBLP CCF conference collector

**Files:**
- Modify: `main.py: source weight, DBLP feed/parser helpers, collect_items`
- Create: `tests/test_ccf_conference_collection.py`

**Interfaces:**
- Produces: `fetch_ccf_conferences(session, since, until, max_items, profile) -> list[NewsItem]`.
- Consumes: `profile["ccf_conference_tiers"]`, `CCF_CONFERENCES`, `https://dblp.org/feed/new.rss`.
- Produces: source labels `CCF <tier> conference · <abbreviation>` and `NewsItem.published` equal to the DBLP feed timestamp.

- [x] **Step 1: Write failing mocked feed/proceeding tests**

```python
items = main.fetch_ccf_conferences(session, since, until, 4, {
    "ccf_conference_tiers": ("A", "B"),
    "relevance_terms": ["agent"],
    "field_keywords": {"AI": ["agent"]},
    "default_field": "AI",
})
self.assertEqual([item.title for item in items], ["Agent Planning with Verified Tools"])
self.assertEqual(items[0].source, "CCF A conference · AAAI")
self.assertEqual(items[0].published, feed_timestamp)
```

Mock one current A-tier proceeding, one B-tier proceeding, one C-tier proceeding, one stale feed item, and one workshop/companion event. Assert default A+B excludes C, A+B+C includes C, stale and workshop entries are excluded, repeated DOI/title links deduplicate, and `max_items` caps proceeding-page requests/items.

- [x] **Step 2: Run the focused tests to verify red**

Run: `.venv/bin/python -m unittest tests.test_ccf_conference_collection -q`

Expected: failure because `fetch_ccf_conferences` is not defined or not dispatched.

- [x] **Step 3: Implement the isolated collector**

Parse the public RSS feed with the installed `feedparser`; retain entries whose `published_parsed`/`updated_parsed` UTC timestamp is inside `[since, until]` and whose URL matches an allowed catalogue `dblp_path`. Reject event titles matching `workshop`, `workshops`, `companion`, `demo`, `short paper`, `doctoral consortium`, or `poster`, and skip shared-directory records whose key cannot establish a main-proceedings match. Fetch at most `min(max_items, 8)` matching proceedings pages, parse `li.entry.inproceedings` with BeautifulSoup, reject front matter/organization-only records, and create `NewsItem` values with DOI/link/authors when available. Do not claim a publisher date that DBLP does not expose.

Add a source status named `CCF conferences (DBLP)` in `collect_items` only when `ccf_conferences` is enabled. Keep its exception boundary separate so a DBLP failure becomes one failed source status without aborting other collectors.

- [x] **Step 4: Run the focused tests to verify green**

Run: `.venv/bin/python -m unittest tests.test_ccf_conference_collection -q`

Expected: all mocked network cases pass, with no network requests outside test doubles.

### Task 4: Recommendation and dashboard configuration

**Files:**
- Modify: `personalization/recommender.py`
- Modify: `dashboard/views.py`
- Modify: `tests/test_personalization_recommender.py`
- Modify: `tests/test_dashboard_smoke.py`

**Interfaces:**
- Produces: new/recommended computer-science `ResearchProfileInput.source_ids` containing `ccf_conferences` and `ccf_conference_tiers == ("A", "B")`.
- Consumes: dashboard source selection and a selector value in `{("A",), ("A", "B"), ("A", "B", "C")}`.

- [x] **Step 1: Write failing recommendation and UI tests**

```python
self.assertIn("ccf_conferences", recommendation.profile.source_ids)
self.assertEqual(recommendation.profile.ccf_conference_tiers, ("A", "B"))
self.assertIn("CCF 会议等级", source)
self.assertIn("A + B + C", source)
```

Also assert that the CCF selector only appears under the computer-science branch and that the edit form preserves a saved A+B+C selection.

- [x] **Step 2: Run the focused tests to verify red**

Run: `.venv/bin/python -m unittest tests.test_personalization_recommender tests.test_dashboard_smoke -q`

Expected: default source and UI-control assertions fail.

- [x] **Step 3: Add safe defaults and constrained UI controls**

Keep the LLM response schema source-only. In `_build_recommendation`, add `ccf_conferences` to a computer-science recommendation when the source is allowed, then rely on `ResearchProfileInput` for the local A+B default. In onboarding/edit forms, show a selectbox labelled `CCF 会议等级` for computer-science profiles; its value applies when the source is selected. Map labels `A`, `A + B`, and `A + B + C` to validated tuples. Include help text that states the time window means DBLP indexing time and that CCF is a recommendation list, not a paper-quality guarantee.

- [x] **Step 4: Run the focused tests to verify green**

Run: `.venv/bin/python -m unittest tests.test_personalization_recommender tests.test_dashboard_smoke -q`

Expected: user-visible defaults and existing non-CS forms pass their smoke coverage.

### Task 5: Documentation, full validation, and deployment

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-07-29-ccf-conference-source-design.md` only if implementation reveals a necessary factual correction
- Modify: `docs/superpowers/plans/2026-07-29-ccf-conference-source.md` to check completed tasks

- [x] **Step 1: Document the source accurately**

Document the CCF/DBLP source under personalised profiles: default A+B, selectable scopes, CCF 2026 catalogue basis, DBLP indexing-time semantics, main-track exclusion, and the fact that existing users must opt in by saving an edited profile.

- [x] **Step 2: Run focused and full verification**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_ccf_catalogue \
  tests.test_ccf_conference_collection \
  tests.test_personalization_models \
  tests.test_personalization_repository \
  tests.test_personalization_recommender \
  tests.test_dashboard_smoke -q
.venv/bin/python -m unittest discover -s tests -q
.venv/bin/python -m py_compile main.py personalization/ccf_catalogue.py personalization/models.py personalization/repository.py personalization/profile.py personalization/recommender.py dashboard/views.py
git diff --check
```

Expected: all tests and compilation succeed, and the diff has no whitespace errors.

- [x] **Step 3: Validate the running dashboard without changing a profile**

Restart the existing 8501 dashboard service, open a computer-science profile editor, and verify the source label and tier selector render with A+B selected. Do not save a test profile or expose credential-bearing logs.

- [x] **Step 4: Commit and push the implementation**

```bash
git add main.py personalization dashboard tests README.md docs/superpowers
git commit -m "feat: add CCF conference source"
git push origin codex/unified-user-scheduler
git push origin HEAD:main
```
