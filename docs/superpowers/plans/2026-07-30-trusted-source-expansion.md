# Trusted Source Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a five-layer trusted-source catalogue, granular user selection,
source-level task metrics and evidence-separated reports without regressing
the fixed daily or personalised delivery workflows.

**Architecture:** Keep `main.collect_items()` as the single collector. A new
pure catalogue module supplies source metadata and profile scoping; `main.py`
uses it to configure the existing fetchers and a small set of new public API
adapters. The existing profile-version repository persists layer intent and
source-level funnel counts through additive migrations.

**Tech Stack:** Python 3.14, SQLite/libsql (Turso), Streamlit, requests,
feedparser, python-docx and unittest.

## Global Constraints

- Do not change the five fixed profile keys or their default collection path.
- Existing source IDs and existing profile versions must remain readable.
- Never make a paid, login-gated or community source appear as a stable,
  equivalent evidence source.
- Never make real LLM, SMTP or public HTTP calls in tests.
- Every executable new source has mocked success and failure coverage.

---

### Task 1: Define the trusted catalogue

**Files:**
- Create: `personalization/source_catalog.py`
- Modify: `main.py`
- Test: `tests/test_trusted_source_catalog.py`

**Interfaces:**
- Produces `SourceDefinition`, `TRUSTED_SOURCE_LAYERS`,
  `source_definitions_for_profile(profile_key)`, `collectable_source_ids()` and
  `default_source_ids_for_layers(profile_key, layers)`.
- `main.available_source_ids()` returns executable catalogue IDs plus all
  legacy IDs supported for that profile.

- [ ] **Step 1: Write failing catalogue tests**

```python
def test_medical_catalogue_separates_public_papers_from_restricted_indexes():
    sources = {source.id: source for source in source_definitions_for_profile("medicine")}
    assert sources["europe_pmc"].layer == "academic_research"
    assert sources["psycinfo_metadata"].collectable is False
    assert sources["psycinfo_metadata"].access_label == "需要授权"
```

- [ ] **Step 2: Run the focused test and verify it fails because the catalogue is absent.**

- [ ] **Step 3: Add the immutable catalogue and legacy compatibility helpers.**

- [ ] **Step 4: Re-run the focused test and verify it passes.**

### Task 2: Persist layer intent safely

**Files:**
- Modify: `personalization/models.py`
- Modify: `personalization/schema.sql`
- Modify: `personalization/repository.py`
- Modify: `personalization/profile.py`
- Test: `tests/test_personalization_models.py`
- Test: `tests/test_personalization_repository.py`

**Interfaces:**
- `ResearchProfileInput.source_layer_ids: tuple[str, ...]` defaults to `()`.
- Existing database rows return `source_layer_ids == ()`.
- `compose_effective_profile()` expands layer defaults only when concrete
  source IDs are absent from a new saved profile.

- [ ] **Step 1: Write failing round-trip and legacy-migration tests.**
- [ ] **Step 2: Run those tests and confirm the missing field failure.**
- [ ] **Step 3: Add validation, JSON storage and an additive SQLite/libsql migration.**
- [ ] **Step 4: Run the focused tests until green.**

### Task 3: Add provenance-aware public collectors

**Files:**
- Modify: `main.py`
- Test: `tests/test_trusted_source_catalog.py`
- Test: `tests/test_multidisciplinary_catalog.py`

**Interfaces:**
- `NewsItem.source_id` and `NewsItem.source_layer` identify an executable
  catalogue source.
- `SourceStatus` carries `source_id`, `source_layer`, `credibility`, raw,
  matched, deduplicated and selected counts.
- `fetch_europe_pmc`, `fetch_biorxiv`, `fetch_clinical_trials` map public API
  responses to `NewsItem`; failures stay isolated in `collect_items()`.

- [ ] **Step 1: Write mocked parsing, date-boundary and failure-isolation tests per new adapter.**
- [ ] **Step 2: Run each focused test and observe the expected missing-fetcher failure.**
- [ ] **Step 3: Add minimal collectors and register them in `collect_items()`.**
- [ ] **Step 4: Run the collector tests until green.**

### Task 4: Compute and persist source-level funnel metrics

**Files:**
- Modify: `main.py`
- Modify: `personalization/schema.sql`
- Modify: `personalization/repository.py`
- Modify: `personalization/custom_runner.py`
- Test: `tests/test_personalization_models.py`
- Test: `tests/test_personalization_repository.py`
- Test: `tests/test_custom_runner.py`

**Interfaces:**
- `generate_report()` completes source counters after profile filtering,
  canonical deduplication and selection.
- `source_metrics` stores the source ID/layer/credibility and all counts with
  additive defaults.
- `get_delivery_task_metrics()` returns the detailed fields for one run only.

- [ ] **Step 1: Write a failing multi-source duplicate test with literal expected per-source counts.**
- [ ] **Step 2: Run it and verify current `item_count`-only rows cannot satisfy it.**
- [ ] **Step 3: Attribute canonical items to one source and persist the full funnel atomically.**
- [ ] **Step 4: Run runner and repository tests until green.**

### Task 5: Render selectable layers and evidence sections

**Files:**
- Modify: `dashboard/views.py`
- Modify: `main.py`
- Test: `tests/test_dashboard_smoke.py`
- Test: `tests/test_trusted_source_catalog.py`

**Interfaces:**
- Onboarding and edit forms call the same profile-scoped catalogue helper.
- The Word generator renders `官方数据与政策`, `学术研究`, `机构研究`,
  `行业、工程与开源动态`, `社区信号` as separate sections.
- Dashboard task metrics tables show source layer, credibility and all funnel
  counts.

- [ ] **Step 1: Write failing AppTest assertions for grouped source controls and detailed task rows.**
- [ ] **Step 2: Run the tests and observe the flat source-selector behavior fail.**
- [ ] **Step 3: Render the grouped, editable controls, restricted-source notice and metrics fields; preserve all action buttons.**
- [ ] **Step 4: Add report layer sections and run focused tests until green.**

### Task 6: Constrain AI recommendations and document operation

**Files:**
- Modify: `personalization/recommender.py`
- Modify: `personalization/normalization.py`
- Modify: `README.md`
- Modify: `.env.example`
- Test: `tests/test_personalization_recommender.py`
- Test: `tests/test_profile_normalization.py`

**Interfaces:**
- Recommendation schema accepts `source_layer_ids` and only collectable,
  non-community default IDs.
- Normalising old profiles creates one compatible immutable version.

- [ ] **Step 1: Write failing tests that reject community/restricted automatic recommendations.**
- [ ] **Step 2: Run them to observe the prior flat allowlist accept the wrong IDs.**
- [ ] **Step 3: Apply local post-validation and document the access/trust policy.**
- [ ] **Step 4: Run recommender and normalisation tests until green.**

### Task 7: Full verification

**Files:**
- Verify: all modified files

- [ ] **Step 1: Run the complete unittest suite with the project virtual environment.**
- [ ] **Step 2: Compile changed Python modules.**
- [ ] **Step 3: Inspect the diff for credential exposure, legacy-ID compatibility and unintended workflow edits.**
- [ ] **Step 4: Perform a local Streamlit AppTest pass without triggering external dispatch.**
