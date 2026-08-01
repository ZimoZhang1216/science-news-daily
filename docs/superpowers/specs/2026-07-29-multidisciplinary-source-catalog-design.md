# Multidisciplinary Research Profiles and Source Layers Design

## Goal

Extend personalised research dailies from five fixed base profiles to a
maintainable academic catalogue covering all fourteen Chinese academic
disciplines. Add carefully-labelled non-journal sources, and let an operator
describe a user's interests in natural language for an LLM to turn into an
editable profile recommendation.

The five existing fixed reports and existing saved user profiles must keep
their current profile keys, source IDs and delivery behaviour.

## Product decisions

### Academic catalogue

The onboarding UI will show all fourteen first-level disciplines:

1. Philosophy
2. Economics
3. Law
4. Education
5. Literature
6. History
7. Natural sciences
8. Engineering
9. Agriculture
10. Medicine
11. Management
12. Arts
13. Interdisciplinary studies
14. Military science

The existing `chemistry`, `organic_chemistry`, `biology`, `statistics`, and
`business_management` profiles remain selectable specialist presets. Add
`computer_science` as an engineering specialist preset because it has a
distinct source mix and is needed for AI, agents, skills, data engineering,
and open-source updates. Each new first-level profile has a conservative
keyword set and a broad academic index source, rather than pretending that a
small hand-picked journal list represents a whole discipline.

### Source layers and trust boundaries

Every item carries one of three immutable source kinds:

- `academic`: peer-reviewed or scholarly-indexed work. Existing arXiv,
  PubMed and Crossref behaviour is unchanged; OpenAlex is added as a broad
  scholarly index for profiles without a mature journal whitelist.
- `official`: a publisher, scholarly society, laboratory or project-owned RSS
  update. Existing RSS feeds are labelled as official updates.
- `community`: public, attributable discussion or release signal. Hacker News
  stories and releases from a curated list of public GitHub repositories are
  supported. They are never presented as academic evidence.

The report shows the source kind with every item and keeps community material
out of the “today's academic highlights” selection when at least one academic
item is available. A community item may still appear as a clearly-labelled
supplementary signal. One source failure never aborts the report.

New source IDs are `openalex`, `official_rss`, `hackernews`, and
`github_releases`; old IDs (`arxiv`, `pubmed`, `crossref`, `rss`) remain valid.
Source availability is profile-specific. A user can select only sources the
chosen profile has configured; saved legacy source IDs continue to work.

OpenAlex calls its works endpoint with text search plus publication-date and
work-type filters. It is a discovery index, so metadata is treated as
scholarly-indexed rather than proof of peer review. Hacker News uses only
recent `story` results from its public date-sorted API. GitHub collects only
published releases from an explicit profile repository list, never global repo
searches or private repositories.

### Initial profile/source coverage

All fourteen first-level profiles use `openalex` and an appropriate keyword
configuration. Sources are deliberately enabled only where useful:

- Medicine and biological specialist profiles: PubMed, OpenAlex, selected
  Crossref journals and official RSS.
- Natural sciences and engineering: arXiv where a relevant category exists,
  OpenAlex, selected Crossref journals and official RSS.
- Philosophy, economics, law, education, literature, history, agriculture,
  management, arts, interdisciplinary studies and military science: OpenAlex
  plus configured official RSS where a stable public feed exists. No fabricated
  journal claim or generic social feed is used to fill gaps.
- Computer science: arXiv, OpenAlex, selected Crossref journals, official RSS,
  Hacker News and curated GitHub releases. Its fields include AI/agents,
  systems, data management and spatio-temporal data.

The initial catalogue is a taxonomy and source foundation, not a claim that
every discipline has equal daily publication volume. If an area has no fresh,
relevant items, the report says so instead of adding unrelated material.

### AI-assisted profile drafting

The onboarding text field becomes “describe the user's research interests in
one paragraph”. The model receives only the user description and an
allowlisted catalogue of profile IDs, source IDs and profile-specific ISSNs.
It returns strict JSON for the existing editable profile fields: base profile,
research topic, include/exclude keywords, allowed sources, journals, content
preferences and delivery defaults, plus a short Chinese rationale and an
uncertainty note.

The model has no authority to save a profile, send a message, invent a source,
or bypass validation. The operator reviews all suggestions in the existing
form and explicitly saves them. Invalid JSON, unsupported profile/source IDs
and mismatched journal ISSNs fail closed with an operator-safe error.

## Architecture

Keep `main.py` as the report generation integration point and extend its
existing profile-configuration pattern with a central profile/source
catalogue. It owns profile metadata, source availability and source labels,
and `main.py` dispatches source fetchers from that catalogue. This avoids an
unrelated refactor of the stable fixed-report path.

Each fetcher maps external payloads into the existing `NewsItem` model,
including `source_kind`. `collect_items()` keeps its fault isolation and
deduplication flow. Ranking applies a source-kind penalty to community items;
selection prefers academic material for the main report body without changing
the fixed-report output contract.

`personalization.models` validates against the central source-ID allowlist.
`personalization.recommender` prompts with the catalogue-derived per-profile
source options and validates the response through `ResearchProfileInput`.
`dashboard.views` renders the same catalogue labels and source choices for
creation and editing, so the UI and backend cannot drift.

## Data compatibility

No database migration is required. Profile versions already serialize source
IDs as JSON. New source IDs are additive; old rows keep their values and their
original profile key. `NewsItem.source_kind` exists only during generation and
defaults to `academic`, so older fixtures and existing fixed feeds remain
valid.

## Error handling and operational limits

- Each OpenAlex query, Hacker News query, GitHub repository release query and
  RSS feed reports an independent `SourceStatus`.
- Query counts are bounded by `source_limit`; only a small configured number
  of Hacker News terms and GitHub repositories may be requested per run.
- GitHub release data is public. An optional `GITHUB_SOURCE_TOKEN` may be
  documented for higher rate limits, but no token is logged or required for a
  local test run.
- The model recommendation uses the already configured OpenAI-compatible
  provider; no model response or user email address is written to logs.

## Test plan

Add deterministic tests with mocked HTTP payloads for:

- all fourteen first-level profiles and the computer-science specialist being
  available without changing the old five profiles;
- OpenAlex filtering and source-kind mapping;
- Hacker News and GitHub release parsing, date filtering and fault isolation;
- academic material winning over equally-ranked community signals;
- model recommendations accepting only catalogue-provided sources and
  rejecting an unsupported social source;
- dashboard onboarding rendering the new description copy and source labels;
- existing legacy source selections and fixed report profiles remaining valid.

Run the full unittest suite without real model calls, SMTP or external HTTP.

## Non-goals

- No scraping of login-only social platforms, X, WeChat, Xiaohongshu or private
  communities.
- No global social-media search, user-provided arbitrary URLs, or automatic
  following of arbitrary accounts.
- No automatic saving, emailing or changing of a profile from model output.
- No claim that every OpenAlex item is peer-reviewed.
