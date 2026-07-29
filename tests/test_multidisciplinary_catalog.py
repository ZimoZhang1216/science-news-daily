import os
import unittest
from datetime import UTC, datetime
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from docx import Document

import main


FIRST_LEVEL_PROFILE_IDS = {
    "philosophy",
    "economics",
    "law",
    "education",
    "literature",
    "history",
    "natural_sciences",
    "engineering",
    "agriculture",
    "medicine",
    "management",
    "arts",
    "interdisciplinary_studies",
    "military_science",
}


class MultidisciplinaryCatalogueTests(unittest.TestCase):
    def test_all_first_level_disciplines_and_computer_science_are_available(self) -> None:
        self.assertTrue(FIRST_LEVEL_PROFILE_IDS.issubset(main.REPORT_PROFILES))
        self.assertIn("computer_science", main.REPORT_PROFILES)
        self.assertEqual(main.resolve_profile("chemistry")["key"], "chemistry")
        self.assertEqual(main.resolve_profile("business_management")["key"], "business_management")

    def test_computer_science_exposes_its_supported_source_layers(self) -> None:
        self.assertEqual(
            main.available_source_ids("computer_science"),
            (
                "arxiv",
                "pubmed",
                "crossref",
                "rss",
                "openalex",
                "ccf_conferences",
                "official_rss",
                "hackernews",
                "github_releases",
            ),
        )

    def test_economics_exposes_shared_user_selectable_sources(self) -> None:
        self.assertEqual(
            main.available_source_ids("economics"),
            ("arxiv", "pubmed", "openalex", "hackernews"),
        )


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


class RecordingSession:
    def __init__(self, payloads: dict[str, object]) -> None:
        self.payloads = payloads
        self.calls: list[tuple[str, dict[str, object], dict[str, object]]] = []

    def get(
        self,
        url: str,
        params: dict[str, object] | None = None,
        timeout: int = 0,
        **kwargs: object,
    ) -> FakeResponse:
        self.calls.append((url, params or {}, kwargs))
        return FakeResponse(self.payloads[url])


class PublicSourceFetcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.since = datetime(2026, 7, 28, tzinfo=UTC)
        self.until = datetime(2026, 7, 29, tzinfo=UTC)
        self.profile = main.resolve_profile("computer_science")

    def test_openalex_keeps_recent_scholarly_works_and_marks_them_academic(self) -> None:
        session = RecordingSession(
            {
                "https://api.openalex.org/works": {
                    "results": [
                        {
                            "display_name": "Data cleaning with verified repair rules",
                            "publication_date": "2026-07-28",
                            "type": "article",
                            "doi": "https://doi.org/10.1000/example",
                            "id": "https://openalex.org/W1",
                            "primary_location": {"landing_page_url": "https://doi.org/10.1000/example", "source": {"display_name": "Journal of Data Quality"}},
                            "abstract_inverted_index": {"Data": [0], "repair": [1], "study": [2]},
                            "authorships": [{"author": {"display_name": "Ada Lovelace"}}],
                        },
                        {
                            "display_name": "Old database result",
                            "publication_date": "2026-07-20",
                            "type": "article",
                            "id": "https://openalex.org/W2",
                        },
                    ]
                }
            }
        )

        items = main.fetch_openalex(session, self.since, self.until, 10, self.profile)

        self.assertEqual([item.title for item in items], ["Data cleaning with verified repair rules"])
        self.assertEqual(items[0].source_kind, "academic")
        self.assertEqual(items[0].source, "OpenAlex: Journal of Data Quality")
        self.assertEqual(items[0].authors, ["Ada Lovelace"])
        self.assertEqual(session.calls[0][1]["filter"], "from_publication_date:2026-07-28,to_publication_date:2026-07-29,type:article")

    def test_hacker_news_keeps_recent_stories_as_community_signals(self) -> None:
        session = RecordingSession(
            {
                "https://hn.algolia.com/api/v1/search_by_date": {
                    "hits": [
                        {
                            "objectID": "1",
                            "title": "Show HN: a new data repair tool",
                            "url": "https://example.test/data-repair",
                            "created_at": "2026-07-28T12:00:00.000Z",
                            "author": "researcher",
                        },
                        {
                            "objectID": "2",
                            "title": "Old agent framework",
                            "url": "https://example.test/old",
                            "created_at": "2026-07-20T12:00:00.000Z",
                        },
                    ]
                }
            }
        )

        items = main.fetch_hackernews(session, self.since, self.until, 10, self.profile)

        self.assertEqual([item.title for item in items], ["Show HN: a new data repair tool"])
        self.assertEqual(items[0].source_kind, "community")
        self.assertEqual(items[0].source, "Hacker News")
        self.assertEqual(session.calls[0][1]["tags"], "story")

    def test_github_releases_keep_recent_published_releases_as_community_signals(self) -> None:
        session = RecordingSession(
            {
                "https://api.github.com/repos/huggingface/transformers/releases": [
                    {
                        "draft": False,
                        "prerelease": False,
                        "name": "Transformers 5.0",
                        "tag_name": "v5.0.0",
                        "html_url": "https://github.com/huggingface/transformers/releases/tag/v5.0.0",
                        "body": "New agent tooling and model support.",
                        "published_at": "2026-07-28T13:00:00Z",
                        "author": {"login": "huggingface-bot"},
                    },
                    {
                        "draft": False,
                        "name": "Old release",
                        "tag_name": "v4.0.0",
                        "html_url": "https://example.test/old",
                        "published_at": "2026-07-20T13:00:00Z",
                    },
                ]
            }
        )
        profile = {**self.profile, "github_repositories": ["huggingface/transformers"]}

        items = main.fetch_github_releases(session, self.since, self.until, 10, profile)

        self.assertEqual([item.title for item in items], ["Transformers 5.0"])
        self.assertEqual(items[0].source_kind, "community")
        self.assertEqual(items[0].source, "GitHub Release: huggingface/transformers")

    def test_github_source_token_is_sent_only_to_github(self) -> None:
        session = RecordingSession({"https://api.github.com/repos/example/project/releases": []})
        profile = {"github_repositories": ["example/project"]}

        with unittest.mock.patch.dict(os.environ, {"GITHUB_SOURCE_TOKEN": "test-token"}, clear=False):
            main.fetch_github_releases(session, self.since, self.until, 10, profile)

        self.assertEqual(session.calls[0][0], "https://api.github.com/repos/example/project/releases")
        self.assertEqual(session.calls[0][2]["headers"]["Authorization"], "Bearer test-token")

    def test_academic_material_wins_over_an_equally_scored_community_signal(self) -> None:
        profile = {
            "field_keywords": {"测试": ["data"]},
            "relevance_terms": ["data"],
            "source_weights": {"OpenAlex": 50, "Hacker News": 50},
            "default_field": "测试",
        }
        academic = main.NewsItem(
            "A data result",
            "OpenAlex",
            self.until,
            "https://example.test/academic",
            abstract="data",
            source_kind="academic",
        )
        community = main.NewsItem(
            "Z data announcement",
            "Hacker News",
            self.until,
            "https://example.test/community",
            abstract="data",
            source_kind="community",
        )

        selected = main.prepare_items([community, academic], 1, self.until, profile, min_items=1)

        self.assertEqual([item.source_kind for item in selected], ["academic"])

    def test_collect_items_isolates_a_public_source_failure(self) -> None:
        profile = {
            "enabled_source_ids": ("openalex", "hackernews", "github_releases"),
            "openalex_query_terms": ["agent"],
            "community_query_terms": ["agent"],
            "github_repositories": ["example/project"],
        }
        academic = main.NewsItem("An academic agent result", "OpenAlex", self.until, "https://example.test/a")
        release = main.NewsItem(
            "Project release", "GitHub Release: example/project", self.until, "https://example.test/r", source_kind="community"
        )
        with (
            patch.object(main, "build_session", return_value=object()),
            patch.object(main, "fetch_openalex", return_value=[academic]),
            patch.object(main, "fetch_hackernews", side_effect=RuntimeError("temporary API error")),
            patch.object(main, "fetch_github_releases", return_value=[release]),
        ):
            items, statuses = main.collect_items(
                SimpleNamespace(source_limit=10), self.since, self.until, profile
            )

        self.assertEqual([item.title for item in items], ["An academic agent result", "Project release"])
        self.assertTrue(next(status for status in statuses if status.name == "Hacker News").success is False)
        self.assertEqual(next(status for status in statuses if status.name == "GitHub Releases").item_count, 1)

    def test_document_labels_a_community_item_as_a_signal_not_academic_evidence(self) -> None:
        item = main.NewsItem(
            "Project release",
            "GitHub Release: example/project",
            self.until,
            "https://example.test/release",
            abstract="Release note.",
            source_kind="community",
            field_name="系统与软件工程",
            item_id="N001",
            comment="这是一个公开发布信号。",
        )
        profile = main.resolve_profile("computer_science")
        with TemporaryDirectory() as temporary_directory:
            output_path = main.create_document(
                [item],
                {"top_ids": ["N001"], "field_summaries": []},
                date(2026, 7, 29),
                Path(temporary_directory),
                profile,
            )
            rendered = "\n".join(paragraph.text for paragraph in Document(output_path).paragraphs)

        self.assertIn("社区信号", rendered)
        self.assertIn("GitHub Release: example/project", rendered)

    def test_document_does_not_place_a_community_signal_in_academic_highlights(self) -> None:
        academic = main.NewsItem(
            "Peer-reviewed data result",
            "OpenAlex: Journal of Testing",
            self.until,
            "https://example.test/paper",
            abstract="data",
            source_kind="academic",
            field_name="数据管理与时空数据",
            item_id="N001",
            comment="学术研究。",
        )
        community = main.NewsItem(
            "Community launch",
            "Hacker News",
            self.until,
            "https://example.test/community",
            abstract="data",
            source_kind="community",
            field_name="数据管理与时空数据",
            item_id="N002",
            comment="社区信号。",
        )
        with TemporaryDirectory() as temporary_directory:
            output_path = main.create_document(
                [academic, community],
                {"top_ids": ["N002"], "field_summaries": []},
                date(2026, 7, 29),
                Path(temporary_directory),
                main.resolve_profile("computer_science"),
            )
            rendered = "\n".join(paragraph.text for paragraph in Document(output_path).paragraphs)

        highlight_text = rendered.split("分领域摘要", maxsplit=1)[0]
        self.assertIn("Peer-reviewed data result", highlight_text)
        self.assertNotIn("Community launch", highlight_text)


if __name__ == "__main__":
    unittest.main()
