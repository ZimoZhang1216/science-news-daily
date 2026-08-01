import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import main
import requests


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.content = text.encode("utf-8")

    def raise_for_status(self) -> None:
        return None


class RecordingSession:
    def __init__(self, responses: dict[str, str | Exception]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str, **_: object) -> FakeResponse:
        self.calls.append(url)
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return FakeResponse(response)


FEED_URL = "https://dblp.org/feed/new.rss"
AAAI_PAGE = "https://dblp.org/db/conf/aaai/aaai2026.html"
EMNLP_PAGE = "https://dblp.org/db/conf/emnlp/emnlp2026.html"
AISTATS_PAGE = "https://dblp.org/db/conf/aistats/aistats2026.html"
ICSE_SEIS_PAGE = "https://dblp.org/db/conf/icse/seis2026.html"

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item><title>AAAI 2026</title><link>https://dblp.org/db/conf/aaai/aaai2026.html</link><pubDate>Tue, 28 Jul 2026 10:00:00 +0000</pubDate></item>
  <item><title>EMNLP 2026</title><link>https://dblp.org/db/conf/emnlp/emnlp2026.html</link><pubDate>Tue, 28 Jul 2026 11:00:00 +0000</pubDate></item>
  <item><title>AISTATS 2026</title><link>https://dblp.org/db/conf/aistats/aistats2026.html</link><pubDate>Tue, 28 Jul 2026 12:00:00 +0000</pubDate></item>
  <item><title>AAAI (Workshops) 2026</title><link>https://dblp.org/db/conf/aaai/aaai2026w.html</link><pubDate>Tue, 28 Jul 2026 13:00:00 +0000</pubDate></item>
  <item><title>AAAI 2025</title><link>https://dblp.org/db/conf/aaai/aaai2025.html</link><pubDate>Tue, 14 Jul 2026 13:00:00 +0000</pubDate></item>
</channel></rss>"""

AAAI_HTML = """
<ul class="publ-list">
  <li class="entry inproceedings">
    <cite class="data" itemprop="headline">
      <span itemprop="author"><span itemprop="name">Ada Lovelace</span></span>:
      <span class="title" itemprop="name">Agent Planning with Verified Tools.</span>
    </cite>
    <a itemprop="url" href="https://doi.org/10.1000/aaai.agent">paper</a>
  </li>
  <li class="entry inproceedings">
    <cite class="data" itemprop="headline"><span class="title" itemprop="name">Front Matter and Conference Organization.</span></cite>
  </li>
</ul>
"""

EMNLP_HTML = """
<ul class="publ-list"><li class="entry inproceedings">
  <cite class="data" itemprop="headline"><span class="title" itemprop="name">Empirical Language Modelling.</span></cite>
  <a itemprop="url" href="https://doi.org/10.1000/emnlp.paper">paper</a>
</li></ul>
"""

AISTATS_HTML = """
<ul class="publ-list"><li class="entry inproceedings">
  <cite class="data" itemprop="headline"><span class="title" itemprop="name">Agent Uncertainty Estimation.</span></cite>
  <a itemprop="url" href="https://doi.org/10.1000/aistats.agent">paper</a>
</li></ul>
"""

ICSE_TRACK_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item><title>ICSE-SEIS 2026</title><link>https://dblp.org/db/conf/icse/seis2026.html</link><pubDate>Tue, 28 Jul 2026 10:00:00 +0000</pubDate></item>
</channel></rss>"""

PARTIAL_FAILURE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item><title>AAAI 2026</title><link>https://dblp.org/db/conf/aaai/aaai2026.html</link><pubDate>Tue, 28 Jul 2026 10:00:00 +0000</pubDate></item>
  <item><title>EMNLP 2026</title><link>https://dblp.org/db/conf/emnlp/emnlp2026.html</link><pubDate>Tue, 28 Jul 2026 11:00:00 +0000</pubDate></item>
</channel></rss>"""


class CcfConferenceCollectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.since = datetime(2026, 7, 28, tzinfo=UTC)
        self.until = datetime(2026, 7, 29, tzinfo=UTC)
        self.profile = {
            "ccf_conference_tiers": ("A", "B"),
            "relevance_terms": ["agent"],
            "field_keywords": {"AI": ["agent"]},
            "default_field": "AI",
        }

    def test_collector_uses_dblp_indexing_time_and_default_a_b_scope(self) -> None:
        session = RecordingSession(
            {FEED_URL: RSS, AAAI_PAGE: AAAI_HTML, EMNLP_PAGE: EMNLP_HTML, AISTATS_PAGE: AISTATS_HTML}
        )

        items = main.fetch_ccf_conferences(session, self.since, self.until, 4, self.profile)

        self.assertEqual([item.title for item in items], ["Agent Planning with Verified Tools."])
        self.assertEqual(items[0].source, "CCF A conference · AAAI")
        self.assertEqual(items[0].published, datetime(2026, 7, 28, 10, 0, tzinfo=UTC))
        self.assertEqual(items[0].doi, "10.1000/aaai.agent")
        self.assertEqual(items[0].authors, ["Ada Lovelace"])
        self.assertNotIn(AISTATS_PAGE, session.calls)
        self.assertNotIn("https://dblp.org/db/conf/aaai/aaai2026w.html", session.calls)

    def test_collector_includes_c_only_when_operator_selects_a_b_c(self) -> None:
        session = RecordingSession(
            {FEED_URL: RSS, AAAI_PAGE: AAAI_HTML, EMNLP_PAGE: EMNLP_HTML, AISTATS_PAGE: AISTATS_HTML}
        )
        profile = {**self.profile, "ccf_conference_tiers": ("A", "B", "C")}

        items = main.fetch_ccf_conferences(session, self.since, self.until, 4, profile)

        self.assertEqual(
            [item.title for item in items],
            ["Agent Planning with Verified Tools.", "Agent Uncertainty Estimation."],
        )
        self.assertEqual(items[1].source, "CCF C conference · AISTATS")
        self.assertIn(AISTATS_PAGE, session.calls)

    def test_collector_caps_proceedings_work_before_fetching_pages(self) -> None:
        session = RecordingSession(
            {FEED_URL: RSS, AAAI_PAGE: AAAI_HTML, EMNLP_PAGE: EMNLP_HTML, AISTATS_PAGE: AISTATS_HTML}
        )

        main.fetch_ccf_conferences(session, self.since, self.until, 1, self.profile)

        self.assertEqual(session.calls, [FEED_URL, AAAI_PAGE])

    def test_collector_rejects_a_satellite_track_under_a_ccf_venue_path(self) -> None:
        session = RecordingSession({FEED_URL: ICSE_TRACK_RSS})

        items = main.fetch_ccf_conferences(session, self.since, self.until, 4, self.profile)

        self.assertEqual(items, [])
        self.assertEqual(session.calls, [FEED_URL])

    def test_collector_keeps_previous_results_when_one_proceedings_page_fails(self) -> None:
        session = RecordingSession(
            {
                FEED_URL: PARTIAL_FAILURE_RSS,
                AAAI_PAGE: AAAI_HTML,
                EMNLP_PAGE: requests.ConnectionError("temporary DBLP error"),
            }
        )

        items = main.fetch_ccf_conferences(session, self.since, self.until, 4, self.profile)

        self.assertEqual([item.title for item in items], ["Agent Planning with Verified Tools."])
        self.assertEqual(session.calls, [FEED_URL, AAAI_PAGE, EMNLP_PAGE])

    def test_collect_items_requires_explicit_ccf_source_enablement(self) -> None:
        profile = {**main.resolve_profile("computer_science"), "enabled_source_ids": ()}
        with (
            patch.object(main, "build_session", return_value=object()),
            patch.object(main, "fetch_arxiv", return_value=[]),
            patch.object(main, "fetch_pubmed", return_value=[]),
            patch.object(main, "fetch_crossref", return_value=([], [])),
            patch.object(main, "fetch_rss", return_value=([], [])),
            patch.object(main, "fetch_openalex", return_value=[]),
            patch.object(main, "fetch_hackernews", return_value=[]),
            patch.object(main, "fetch_github_releases", return_value=[]),
            patch.object(main, "fetch_ccf_conferences") as fetch_ccf,
        ):
            main.collect_items(SimpleNamespace(source_limit=10), self.since, self.until, profile)

        fetch_ccf.assert_not_called()

    def test_collect_items_isolates_a_ccf_source_failure(self) -> None:
        profile = {
            "enabled_source_ids": ("openalex", "ccf_conferences"),
            "openalex_query_terms": ["agent"],
            "ccf_conference_tiers": ("A", "B"),
        }
        academic = main.NewsItem("An academic agent result", "OpenAlex", self.until, "https://example.test/a")
        with (
            patch.object(main, "build_session", return_value=object()),
            patch.object(main, "fetch_openalex", return_value=[academic]),
            patch.object(main, "fetch_ccf_conferences", side_effect=RuntimeError("temporary DBLP error")),
        ):
            items, statuses = main.collect_items(
                SimpleNamespace(source_limit=10), self.since, self.until, profile
            )

        self.assertEqual([item.title for item in items], ["An academic agent result"])
        ccf_status = next(status for status in statuses if status.name == "CCF conferences (DBLP)")
        self.assertFalse(ccf_status.success)
