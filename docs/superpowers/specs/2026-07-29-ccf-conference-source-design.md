# CCF Conference Source Design

## Goal

Add an optional academic source for the `computer_science` profile that finds newly indexed full/regular papers from venues in the CCF recommended international conference catalogue. Newly created computer-science profiles select CCF A+B conferences by default, with a user-selectable A, A+B, or A+B+C scope.

## Source and time semantics

- The venue catalogue is a versioned, in-repository representation of the official CCF recommended conference catalogue. It stores the CCF category, tier, display name, aliases, and DBLP conference path. It is explicitly labelled with the CCF catalogue version/date it represents.
- DBLP's public `new.rss` feed is used to discover newly added conference-proceeding records. The record is eligible only when its DBLP feed timestamp falls within the profile's existing 1–60 day information window.
- A matching DBLP proceeding page provides its contained publication metadata. The displayed source is `CCF <tier> conference · <venue>` and its date is the DBLP indexing timestamp, not an asserted publisher publication date.
- Only CCF A/B/C entries configured in the selected scope are collected. Records that look like workshops, demos, short papers, companion proceedings, or other non-main tracks are excluded when DBLP's proceeding title makes that distinction available. This reflects CCF's stated scope for full/regular conference papers.
- Source failures are isolated and reported just like existing academic sources. A DBLP request failure cannot prevent arXiv, OpenAlex, or other enabled sources from completing.

## User configuration

- Add `ccf_conferences` to the academic source catalogue, but make it available only for `computer_science` profiles.
- Add `ccf_conference_tiers` to immutable research profile versions as a validated list of `A`, `B`, and `C` values. Its default is `("A", "B")`.
- The dashboard presents a constrained selector only when the computer-science profile has the CCF source enabled: `A`, `A + B` (default), and `A + B + C`.
- New/recommended computer-science profiles include `ccf_conferences` and `A+B` by default. Existing saved profiles retain their existing source selections; they gain the default tier value for data compatibility but are not silently opted into a new network source.
- The recommendation model does not choose raw tier data. It can select `ccf_conferences` for computer-science users, and the validated local default remains A+B unless the operator changes it in the edit form.

## Data and compatibility

- Add `ccf_conference_tiers_json TEXT NOT NULL DEFAULT '["A","B"]'` to `research_profiles`; SQLite and Turso use the repository's existing additive migration path.
- Persist, load, clone, and sync this field through `ResearchProfileInput`, repository row serialization, and profile composition.
- A local replica that has not received the migration must fall back to the in-memory A+B default, matching the existing stale-replica approach for `lookback_days`.

## Collection boundary

- The CCF catalogue belongs in a focused `personalization/ccf_catalogue.py` module instead of `main.py`, so CCF versioning and aliases are not spread across the report runtime and dashboard.
- `main.fetch_ccf_conferences` receives `(session, since, until, max_items, profile)`, checks the enabled source and selected tiers, parses DBLP's feed and matching proceeding pages, creates `NewsItem` values, and applies the existing relevance filtering, deduplication, ranking, and daily-history mechanisms.
- The collector has a strict cap on matching proceedings/pages per run derived from `max_items`, preventing a broad 60-day window from creating an unbounded workflow.

## UI and report behaviour

- The user profile form uses the existing source multi-select plus the tier selector. The dashboard labels this source as `CCF 推荐会议（DBLP 新收录）` and explains that the time window means DBLP indexing time.
- A report title remains AI-generated and never copies raw source/tier configuration into the title. Individual entries retain their CCF tier/venue in source metadata for auditability.
- Fixed subject dailies and all non-computer-science personalised profiles have unchanged source selections and collection paths.

## Verification

- Unit tests cover catalogue tier filtering, source availability, input validation/defaulting, database migration/load compatibility, dashboard tier-control visibility, recommendation defaults, and profile composition.
- Network-free collector tests mock the DBLP RSS/proceeding responses to verify time filtering, A+B default behaviour, A/B/C selection, main-track exclusion, source labels, per-run cap, deduplication, and source-failure isolation.
- Existing full test suite remains green. No tests send email, call a paid model, or require a live DBLP/CCF endpoint.

