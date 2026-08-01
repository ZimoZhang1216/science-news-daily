# Trusted Source Expansion Design

## Goal

Turn the existing flat personalised-source selection into a trustworthy,
maintainable catalogue. Every catalogue record has a clear evidence layer,
access boundary, discipline scope and collection contract. Existing fixed
reports, profile versions, schedules, previews, PDFs and delivery controls
remain unchanged.

## Evidence layers

The user-facing layers are deliberately distinct:

1. `official_data_policy` — primary government, regulator, intergovernmental,
   public-health, standards and funding-agency data, notices or reports.
2. `academic_research` — papers, preprints, scholarly indexes and conference
   catalogues. A preprint remains labelled as a preprint; indexed metadata is
   not promoted to peer review.
3. `institutional_research` — university centres, think tanks, working-paper
   series and public research reports.
4. `industry_engineering` — official product, standards, professional-association
   and allowlisted open-source release updates.
5. `community_signal` — attributable public community discussion. It is never
   rendered as evidence or promoted automatically to the daily highlights.

`SourceDefinition` is immutable catalogue data. It records a stable ID,
Chinese name, layer, applicable profile keys, topic scope, acquisition method,
key requirement, update cadence, default credibility (1–5), access/copyright
notice, whether it is collectable, default selection state and fallback policy.
The catalogue includes all requested discipline groups. Only sources with a
verified public API, RSS feed or long-lived public endpoint are collectable and
default-enabled. Subscription-only or login-gated sources are displayed as
“需要授权” and cannot be saved as executable selections.

## Compatibility and selection model

`research_profiles.source_ids_json` remains the source of truth for concrete
source choices. Add `source_layer_ids_json` as an additive profile-version
field so the UI can preserve layer-level intent. Legacy profile versions get
an empty layer list and retain their current generic IDs (`arxiv`, `pubmed`,
`crossref`, `rss`, `openalex`, `official_rss`, `hackernews`,
`github_releases`, `ccf_conferences`) unchanged.

The dashboard presents a profile-scoped catalogue grouped by evidence layer.
Selecting a layer adds its stable public default sources; operators can then
add or remove individual collectable sources. Community sources require an
explicit opt-in and show a warning. The recommender receives only public,
collectable sources in the first four layers; model output is locally
validated and never saved without the existing operator confirmation.

## Collection and provenance

`main.collect_items()` remains the only collection orchestrator. A registry
maps catalogue IDs to existing or new fetch adapters; no second scraper or
parallel pipeline is introduced. Existing collectors receive stable source
IDs and layers. The first implemented additions are public Europe PMC,
bioRxiv/medRxiv and ClinicalTrials.gov adapters, plus catalogue-driven public
RSS feeds. The catalogue can list authenticated or non-automatable sources
without routing them to a fetcher.

Each `NewsItem` has `source_id` and `source_layer`. `SourceStatus` tracks its
catalogue identity and the five counters: raw, profile-matched, deduplicated,
selected and failure reason. For duplicates, one canonical retained item owns
the deduplicated/selected count so per-source totals do not double count.

## Presentation and observability

Word reports render evidence-layer sections in the five-layer order. Academic
items remain eligible for highlights; community items are excluded whenever a
non-community item exists. Task detail and aggregate source metrics display
source, layer, credibility, raw, matched, deduplicated, selected and failure
reason. Historical rows render with zero/empty new metrics safely.

## Verification

Every collectable new source uses a mocked HTTP fixture for parsing, date
filtering, source attribution and isolated failure. Catalogue-only authorised
sources are tested as non-collectable and visibly restricted. Repository,
runner and Streamlit tests exercise version migration, metric persistence,
layer controls and unchanged delivery actions. The suite does not call an LLM,
SMTP server or public source endpoint.
