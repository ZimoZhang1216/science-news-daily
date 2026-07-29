# Multidisciplinary Source Catalogue Implementation Plan

**Goal:** Add fourteen academic discipline presets, source layers, and safe AI-assisted profile drafting without changing existing fixed reports.

**Architecture:** Centralise catalogue metadata in `main.py`-compatible helpers, add additive fetchers for OpenAlex/public community signals, then expose the same allowlist in models, recommender and dashboard. Source kind travels with each `NewsItem` and is used only for presentation/ranking.

**Tech stack:** Python 3.14, requests, feedparser, python-docx, Streamlit, unittest.

## Tasks

### 1. Catalogue and source contracts

- [x] Write failing tests proving all fourteen first-level profiles and `computer_science` resolve, while legacy profiles keep their keys.
- [x] Add profile labels, source labels and source-availability helpers plus conservative profile definitions.
- [x] Run the focused tests and verify green.

### 2. Academic and public-source fetchers

- [x] Write failing mocked-HTTP tests for OpenAlex, Hacker News and GitHub release parsing, timestamp filtering and source-kind labels.
- [x] Add bounded, independently-failing fetchers and wire them into `collect_items()` behind new source IDs.
- [x] Add an academic-over-community selection test and implement the minimum rank/selection rule.
- [x] Run focused tests and verify green.

### 3. Profile and AI recommendation validation

- [x] Write failing tests for new source-ID normalisation and recommender rejection of a source unavailable to its selected profile.
- [x] Expand model validation and prompt generation from the catalogue-derived allowlists.
- [x] Run focused tests and verify green.

### 4. Dashboard and report provenance

- [x] Write failing dashboard smoke tests for the description-first onboarding copy and source labels.
- [x] Render catalogue labels and profile-specific sources in creation/editing, and show source kind in report items.
- [x] Run focused tests and verify green.

### 5. Documentation and regression verification

- [x] Update README and `.env.example` with source layers, OpenAlex/GitHub operational limits, and AI drafting boundaries.
- [x] Run `python -m unittest discover -s tests -v` without external requests, model calls or SMTP.
- [x] Inspect the final diff for secret exposure, compatibility regressions and documentation drift.
