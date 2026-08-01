import os
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from docx import Document

import main
from personalization.models import (
    ProfileRecommendation,
    RecommendationRequest,
    ResearchProfileInput,
    ScheduleInput,
    UserInput,
)
import personalization.profile as profile_rules
from personalization.profile import compose_effective_profile, item_matches_research_profile


class PersonalizationModelTests(unittest.TestCase):
    def valid_profile(
        self,
        *,
        lookback_days: int = 3,
        candidate_limit: int = 300,
        ccf_conference_tiers: tuple[str, ...] = ("A", "B"),
        source_layer_ids: str | tuple[str, ...] = (),
    ) -> ResearchProfileInput:
        return ResearchProfileInput.from_form(
            base_profile="chemistry",
            research_topic="Lithium metal batteries",
            include_keywords="",
            exclude_keywords="",
            source_ids=(),
            journal_ids=(),
            content_preferences=(),
            max_items=12,
            candidate_limit=candidate_limit,
            llm_provider="openai",
            llm_model="gpt-5.4-mini",
            output_formats=("docx",),
            lookback_days=lookback_days,
            ccf_conference_tiers=ccf_conference_tiers,
            source_layer_ids=source_layer_ids,
        )

    def test_recommendation_request_requires_the_three_operator_inputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "research_topic is required"):
            RecommendationRequest.from_form("张三", "reader@example.com", "")

    def test_empty_model_response_records_a_deliverable_failure_reason(self) -> None:
        item = main.NewsItem(
            "Battery interface transport",
            "arXiv",
            datetime(2026, 7, 28, tzinfo=timezone.utc),
            "https://example.test/battery",
            abstract="Battery ion transport study.",
            item_id="N001",
        )

        class EmptyResponseClient:
            calls = 0

            class chat:
                class completions:
                    @staticmethod
                    def create(**_kwargs):
                        EmptyResponseClient.calls += 1
                        return type(
                            "Response",
                            (),
                            {"choices": [type("Choice", (), {"message": type("Message", (), {"content": ""})()})()]},
                        )()

        with (
            patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=False),
            patch.object(main, "OpenAI", return_value=EmptyResponseClient()),
        ):
            payload = main.generate_ai_summaries(
                [item],
                "deepseek-v4-flash",
                10,
                main.resolve_profile("chemistry"),
                provider_override="deepseek",
            )

        self.assertFalse(payload["ai_generated"])
        self.assertEqual(payload["ai_error"], "deepseek: empty response content")
        self.assertEqual(EmptyResponseClient.calls, 2)

    def test_recommendation_result_uses_a_disabled_schedule(self) -> None:
        result = ProfileRecommendation(
            profile=self.valid_profile(),
            schedule=ScheduleInput.from_form("daily", None, "Asia/Shanghai", "07:30", False),
            rationale="课题聚焦固态电池界面。",
            uncertainty="未指定期刊，因此使用基础学科期刊池。",
        )

        self.assertFalse(result.schedule.enabled)

    def test_recommendation_result_rejects_an_enabled_schedule(self) -> None:
        with self.assertRaisesRegex(ValueError, "schedule.enabled must be False"):
            ProfileRecommendation(
                profile=self.valid_profile(),
                schedule=ScheduleInput.from_form("daily", None, "Asia/Shanghai", "07:30", True),
                rationale="课题聚焦固态电池界面。",
                uncertainty="未指定期刊，因此使用基础学科期刊池。",
            )

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
            lookback_days=60,
        )

        self.assertEqual(profile.include_keywords, ("sei", "solid electrolyte"))
        self.assertEqual(profile.exclude_keywords, ("review",))
        self.assertEqual(profile.lookback_days, 60)
        with self.assertRaisesRegex(ValueError, "base_profile"):
            ResearchProfileInput.from_form(
                base_profile="unknown",
                research_topic="x",
                include_keywords="",
                exclude_keywords="",
                source_ids=(),
                journal_ids=(),
                content_preferences=(),
                max_items=12,
                llm_provider="openai",
                llm_model="gpt-5.4-mini",
                output_formats=("pdf",),
                lookback_days=3,
            )

    def test_profile_input_rejects_lookback_windows_outside_one_to_sixty_days(self) -> None:
        self.assertEqual(self.valid_profile(lookback_days=1).lookback_days, 1)
        self.assertEqual(self.valid_profile(lookback_days=60).lookback_days, 60)
        with self.assertRaisesRegex(ValueError, "lookback_days"):
            self.valid_profile(lookback_days=0)
        with self.assertRaisesRegex(ValueError, "lookback_days"):
            self.valid_profile(lookback_days=61)

    def test_profile_input_persists_a_bounded_candidate_collection_budget(self) -> None:
        profile = self.valid_profile(candidate_limit=500)

        self.assertEqual(profile.candidate_limit, 500)
        with self.assertRaisesRegex(ValueError, "candidate_limit"):
            self.valid_profile(candidate_limit=49)
        with self.assertRaisesRegex(ValueError, "candidate_limit"):
            self.valid_profile(candidate_limit=1001)

    def test_user_keywords_take_priority_in_external_source_queries(self) -> None:
        profile = ResearchProfileInput.from_form(
            base_profile="chemistry",
            research_topic="Flexible electronics",
            include_keywords="flexible electronics; electronic skin",
            exclude_keywords="",
            source_ids=("openalex",),
            journal_ids=(),
            content_preferences=(),
            max_items=12,
            candidate_limit=300,
            llm_provider="openai",
            llm_model="gpt-5.4-mini",
            output_formats=("docx",),
        )

        effective = compose_effective_profile(profile, "usr_test")

        self.assertEqual(effective["openalex_query_terms"][:2], ["flexible electronics", "electronic skin"])

    def test_profile_input_defaults_to_ccf_a_and_b_and_validates_tiers(self) -> None:
        self.assertEqual(self.valid_profile().ccf_conference_tiers, ("A", "B"))
        self.assertEqual(
            self.valid_profile(ccf_conference_tiers=("A", "B", "C")).ccf_conference_tiers,
            ("A", "B", "C"),
        )
        with self.assertRaisesRegex(ValueError, "ccf_conference_tiers"):
            self.valid_profile(ccf_conference_tiers=("B", "A"))
        with self.assertRaisesRegex(ValueError, "ccf_conference_tiers"):
            self.valid_profile(ccf_conference_tiers=())

    def test_profile_input_normalizes_known_source_layers_and_rejects_unknown_layers(self) -> None:
        profile = self.valid_profile(
            source_layer_ids="academic_research; official_data_policy, academic_research"
        )

        self.assertEqual(
            profile.source_layer_ids,
            ("academic_research", "official_data_policy"),
        )
        with self.assertRaisesRegex(ValueError, "source_layer_ids"):
            self.valid_profile(source_layer_ids=("untrusted_layer",))

    def test_profile_input_preserves_a_legacy_directory_only_source(self) -> None:
        profile = ResearchProfileInput.from_form(
            base_profile="economics",
            research_topic="宏观经济与金融动态",
            include_keywords="",
            exclude_keywords="",
            source_ids=("international_statistics",),
            journal_ids=(),
            content_preferences=(),
            max_items=12,
            llm_provider="openai",
            llm_model="gpt-5.4-mini",
            output_formats=("docx",),
        )

        self.assertEqual(profile.source_ids, ("international_statistics",))
        self.assertNotIn("international_statistics", main.available_source_ids("economics"))

    def test_ccf_source_requires_the_computer_science_profile(self) -> None:
        with self.assertRaisesRegex(ValueError, "ccf_conferences"):
            ResearchProfileInput.from_form(
                base_profile="chemistry",
                research_topic="Lithium metal batteries",
                include_keywords="",
                exclude_keywords="",
                source_ids=("ccf_conferences",),
                journal_ids=(),
                content_preferences=(),
                max_items=12,
                llm_provider="openai",
                llm_model="gpt-5.4-mini",
                output_formats=("docx",),
            )

    def test_weekly_schedule_requires_a_weekday_and_valid_timezone(self) -> None:
        with self.assertRaisesRegex(ValueError, "weekday"):
            ScheduleInput.from_form("weekly", None, "Asia/Shanghai", "07:30", True)
        with self.assertRaisesRegex(ValueError, "timezone"):
            ScheduleInput.from_form("daily", None, "Mars/Olympus", "07:30", True)

    def test_user_input_requires_an_email_address(self) -> None:
        user = UserInput.from_form("Alice", "alice@example.test", "active")
        self.assertEqual(user.email, "alice@example.test")
        with self.assertRaisesRegex(ValueError, "email"):
            UserInput.from_form("Alice", "not-an-email", "active")


class PersonalizationProfileTests(unittest.TestCase):
    def make_profile(
        self,
        *,
        source_ids: tuple[str, ...] = (),
        journal_ids: tuple[str, ...] = (),
        content_preferences: tuple[str, ...] = (),
        source_layer_ids: tuple[str, ...] = (),
        include_keywords: str = "",
        exclude_keywords: str = "",
    ) -> ResearchProfileInput:
        return ResearchProfileInput.from_form(
            base_profile="chemistry",
            research_topic="Lithium metal batteries",
            include_keywords=include_keywords,
            exclude_keywords=exclude_keywords,
            source_ids=source_ids,
            journal_ids=journal_ids,
            content_preferences=content_preferences,
            source_layer_ids=source_layer_ids,
            max_items=12,
            llm_provider="openai",
            llm_model="gpt-5.4-mini",
            output_formats=("docx", "pdf"),
        )

    def test_effective_profile_keeps_the_base_title_out_of_the_user_prompt(self) -> None:
        profile = self.make_profile(include_keywords="solid electrolyte", exclude_keywords="review")

        effective = compose_effective_profile(profile, "usr_001")
        base = main.resolve_profile("chemistry")

        self.assertEqual(effective["title"], base["title"])
        self.assertNotIn(profile.research_topic, effective["title"])
        self.assertIn("solid electrolyte", effective["relevance_terms"])
        self.assertNotIn("solid electrolyte", base["relevance_terms"])

    def test_exclude_keyword_wins_and_include_keyword_is_required_when_configured(self) -> None:
        profile = self.make_profile(include_keywords="battery", exclude_keywords="review")

        self.assertFalse(
            item_matches_research_profile(
                main.NewsItem("Battery review", "arXiv", None, "https://e.test/1"), profile
            )
        )
        self.assertFalse(
            item_matches_research_profile(
                main.NewsItem("Protein folding", "arXiv", None, "https://e.test/2"), profile
            )
        )
        self.assertTrue(
            item_matches_research_profile(
                main.NewsItem("Battery interface transport", "arXiv", None, "https://e.test/3"),
                profile,
            )
        )

    def test_explicit_source_selection_allows_current_affairs_fallback_but_keeps_exclusions(self) -> None:
        profile = ResearchProfileInput.from_form(
            base_profile="law",
            research_topic="国际时事政治",
            include_keywords="国际政治,外交,联合国,政策",
            exclude_keywords="sports",
            source_ids=("united_nations",),
            journal_ids=(),
            content_preferences=(),
            max_items=12,
            llm_provider="openai",
            llm_model="gpt-5.4-mini",
            output_formats=("docx",),
            source_layer_ids=("official_data_policy",),
        )
        effective = compose_effective_profile(profile, "usr_001")
        current_affairs = main.NewsItem(
            "Middle East ceasefire talks resume at the United Nations",
            "UN News",
            None,
            "https://example.test/un/1",
            abstract="Diplomatic developments.",
            source_id="united_nations",
        )
        excluded = main.NewsItem(
            "Sports diplomacy highlights", "UN News", None, "https://example.test/un/2"
        )

        self.assertTrue(hasattr(profile_rules, "item_is_custom_fallback_relevant"))
        self.assertTrue(profile_rules.item_is_custom_fallback_relevant(current_affairs, profile, effective))
        self.assertFalse(profile_rules.item_is_custom_fallback_relevant(excluded, profile, effective))

    def test_selected_sources_and_preference_change_only_the_effective_profile(self) -> None:
        profile = self.make_profile(
            source_ids=("pubmed",),
            journal_ids=("0002-7863",),
            content_preferences=("mechanism",),
        )

        effective = compose_effective_profile(profile, "usr_001")

        self.assertEqual(effective["enabled_source_ids"], ("pubmed",))
        self.assertTrue(effective["source_selection_explicit"])
        self.assertEqual([journal["source"] for journal in effective["crossref_journals"]], ["JACS"])
        self.assertIn("mechanism", effective["custom_preference_terms"])

    def test_academic_layer_resolves_registered_public_default_sources(self) -> None:
        profile = self.make_profile(source_layer_ids=("academic_research",))

        effective = compose_effective_profile(profile, "usr_001")

        self.assertEqual(effective["source_layer_ids"], ("academic_research",))
        self.assertEqual(
            effective["enabled_source_ids"],
            ("arxiv", "pubmed", "crossref", "rss", "acs", "rsc", "nature_chemistry"),
        )
        self.assertTrue(effective["source_selection_explicit"])

    def test_concrete_sources_override_layer_defaults_without_expansion(self) -> None:
        profile = self.make_profile(
            source_ids=("openalex", "arxiv"),
            source_layer_ids=("academic_research",),
        )

        effective = compose_effective_profile(profile, "usr_001")

        self.assertEqual(
            effective["enabled_source_ids"],
            ("openalex", "arxiv"),
        )

    def test_community_layer_keeps_an_explicitly_selected_supported_community_source(self) -> None:
        profile = self.make_profile(
            source_ids=("hackernews",),
            source_layer_ids=("community_signal",),
        )

        effective = compose_effective_profile(profile, "usr_001")

        self.assertEqual(effective["enabled_source_ids"], ("hackernews",))
        self.assertTrue(effective["source_selection_explicit"])

    def test_community_layer_is_an_explicit_empty_source_selection(self) -> None:
        profile = self.make_profile(source_layer_ids=("community_signal",))

        effective = compose_effective_profile(profile, "usr_001")

        self.assertEqual(effective["enabled_source_ids"], ())
        self.assertTrue(effective["source_selection_explicit"])

    def test_legacy_empty_source_selection_remains_implicit(self) -> None:
        effective = compose_effective_profile(self.make_profile(), "usr_001")

        self.assertEqual(effective["enabled_source_ids"], ())
        self.assertFalse(effective["source_selection_explicit"])

    def test_effective_computer_science_profile_carries_the_selected_ccf_tiers(self) -> None:
        profile = ResearchProfileInput.from_form(
            base_profile="computer_science",
            research_topic="AI agents and evaluation",
            include_keywords="agent",
            exclude_keywords="",
            source_ids=("ccf_conferences",),
            journal_ids=(),
            content_preferences=(),
            max_items=12,
            llm_provider="openai",
            llm_model="gpt-5.4-mini",
            output_formats=("docx",),
            ccf_conference_tiers=("A", "C"),
        )

        effective = compose_effective_profile(profile, "usr_001")

        self.assertEqual(effective["ccf_conference_tiers"], ("A", "C"))

    def test_shared_sources_use_the_user_research_terms_for_an_academic_profile(self) -> None:
        profile = ResearchProfileInput.from_form(
            base_profile="economics",
            research_topic="Causal inference in development economics",
            include_keywords="cash transfer",
            exclude_keywords="",
            source_ids=("arxiv", "openalex", "hackernews"),
            journal_ids=(),
            content_preferences=(),
            max_items=12,
            llm_provider="openai",
            llm_model="gpt-5.4-mini",
            output_formats=("docx",),
        )

        effective = compose_effective_profile(profile, "usr_001")

        self.assertEqual(effective["enabled_source_ids"], ("arxiv", "openalex", "hackernews"))
        self.assertIn("cash transfer", effective["arxiv_query_terms"])
        self.assertIn("cash transfer", effective["openalex_query_terms"])
        self.assertIn("cash transfer", effective["community_query_terms"])
        self.assertNotIn(profile.research_topic, effective["arxiv_query_terms"])


class CapturingSmtp:
    def __init__(self) -> None:
        self.messages = []

    def __enter__(self) -> "CapturingSmtp":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def login(self, username: str, password: str) -> None:
        return None

    def send_message(self, message):
        self.messages.append(message)
        return {}


class ReportGenerationApiTests(unittest.TestCase):
    def test_email_success_log_does_not_include_recipient_addresses(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")

        self.assertNotIn('LOGGER.info("Sent report email to %s', source)
        self.assertIn('"Sent report email to %d recipient(s) with PDF attachment %s"', source)

    def setUp(self) -> None:
        self.tempdir = TemporaryDirectory()
        self.profile = main.resolve_profile("chemistry")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_document_uses_the_ai_report_title_instead_of_the_profile_title(self) -> None:
        item = main.NewsItem(
            "Economic policy evidence",
            "OpenAlex",
            datetime(2026, 7, 28, tzinfo=timezone.utc),
            "https://e.test/economics",
            abstract="Recent economics research.",
            item_id="N001",
        )
        profile = {**main.resolve_profile("economics"), "title": "经济学科研资讯日报"}
        output_path = main.create_document(
            [item],
            {
                "top_ids": [item.item_id],
                "field_summaries": [],
                "report_title": "全球不确定性下的外商投资观察",
            },
            date(2026, 7, 28),
            Path(self.tempdir.name),
            profile,
        )

        titles = [paragraph.text for paragraph in Document(output_path).paragraphs]

        self.assertIn("全球不确定性下的外商投资观察", titles)
        self.assertNotIn(profile["title"], titles)

    def test_generate_report_applies_user_filter_after_existing_collection(self) -> None:
        item = main.NewsItem(
            "Battery interface transport",
            "arXiv",
            datetime(2026, 7, 28, tzinfo=timezone.utc),
            "https://e.test/b",
            abstract="Battery ion transport study.",
        )
        options = main.ReportGenerationOptions(
            days=1,
            max_items=10,
            min_items=1,
            source_limit=10,
            max_ai_items=10,
            llm_provider="openai",
            model="",
            report_date=date(2026, 7, 28),
            output_dir=Path(self.tempdir.name),
            require_ai=False,
            no_openai=False,
        )
        output_path = Path(self.tempdir.name) / "report.docx"
        payload = main.fallback_report_payload([item], self.profile)
        with (
            patch.object(main, "collect_items", return_value=([item], [main.SourceStatus("arXiv", True, 1)])),
            patch("network_check.run_network_checks", return_value=type("Diagnostics", (), {"network_ok": True, "summary_lines": lambda self: []})()),
            patch.object(main, "generate_ai_summaries", return_value=payload),
            patch.object(main, "apply_ai_scientific_notation", return_value=False),
            patch.object(main, "create_document", return_value=output_path),
        ):
            result = main.generate_report(
                options,
                self.profile,
                item_filter=lambda candidate: "battery" in candidate.title.casefold(),
            )

        self.assertEqual(result.selected_count, 1)
        self.assertEqual(result.output_path, output_path)

    def test_generate_report_falls_back_to_base_profile_results_when_keywords_are_too_narrow(self) -> None:
        item = main.NewsItem(
            "Economic policy evidence",
            "OpenAlex",
            datetime(2026, 7, 28, tzinfo=timezone.utc),
            "https://e.test/economics",
            abstract="Recent economics research.",
        )
        options = main.ReportGenerationOptions(
            days=3,
            max_items=10,
            min_items=1,
            source_limit=10,
            max_ai_items=10,
            llm_provider="openai",
            model="",
            report_date=date(2026, 7, 28),
            output_dir=Path(self.tempdir.name),
            require_ai=False,
            no_openai=False,
        )
        output_path = Path(self.tempdir.name) / "report.docx"
        payload = main.fallback_report_payload([item], self.profile)
        with (
            patch.object(main, "collect_items", return_value=([item], [main.SourceStatus("OpenAlex", True, 1)])),
            patch("network_check.run_network_checks", return_value=type("Diagnostics", (), {"network_ok": True, "summary_lines": lambda self: []})()),
            patch.object(main, "generate_ai_summaries", return_value=payload),
            patch.object(main, "apply_ai_scientific_notation", return_value=False),
            patch.object(main, "create_document", return_value=output_path),
        ):
            result = main.generate_report(options, self.profile, item_filter=lambda _candidate: False)

        self.assertEqual(result.selected_count, 1)
        self.assertEqual(result.output_path, output_path)
        self.assertEqual(result.matched_count, 0)
        self.assertTrue(result.profile_filter_fallback)
        self.assertEqual(
            (
                result.source_statuses[0].matched_count,
                result.source_statuses[0].deduplicated_count,
                result.source_statuses[0].selected_count,
            ),
            (1, 1, 1),
        )

    def test_generate_report_supplements_a_small_keyword_match_without_readding_exclusions(self) -> None:
        published = datetime(2026, 7, 28, tzinfo=timezone.utc)
        items = [
            main.NewsItem("Battery interface transport", "arXiv", published, "https://e.test/1", abstract="Battery study."),
            main.NewsItem("Battery electrolyte mechanics", "arXiv", published, "https://e.test/2", abstract="Battery study."),
            main.NewsItem("Catalysis reaction mechanism", "arXiv", published, "https://e.test/3", abstract="Catalysis study."),
            main.NewsItem("Molecular synthesis method", "arXiv", published, "https://e.test/4", abstract="Synthesis study."),
            main.NewsItem("Electrolyte ion transport", "arXiv", published, "https://e.test/5", abstract="Electrolyte study."),
            main.NewsItem("Battery review", "arXiv", published, "https://e.test/6", abstract="Excluded review."),
        ]
        options = main.ReportGenerationOptions(
            days=3,
            max_items=10,
            min_items=1,
            source_limit=10,
            max_ai_items=10,
            llm_provider="openai",
            model="",
            report_date=date(2026, 7, 28),
            output_dir=Path(self.tempdir.name),
            require_ai=False,
            no_openai=False,
        )
        output_path = Path(self.tempdir.name) / "report.docx"
        with (
            patch.object(main, "collect_items", return_value=(items, [main.SourceStatus("arXiv", True, len(items))])),
            patch("network_check.run_network_checks", return_value=type("Diagnostics", (), {"network_ok": True, "summary_lines": lambda self: []})()),
            patch.object(main, "generate_ai_summaries", return_value=main.fallback_report_payload(items, self.profile)),
            patch.object(main, "apply_ai_scientific_notation", return_value=False),
            patch.object(main, "create_document", return_value=output_path),
        ):
            result = main.generate_report(
                options,
                self.profile,
                item_filter=lambda item: "battery" in item.title.casefold() and "review" not in item.title.casefold(),
                supplement_filter=lambda item: "review" not in item.title.casefold(),
            )

        self.assertEqual(result.matched_count, 2)
        self.assertEqual(result.selected_count, 5)
        self.assertTrue(result.profile_filter_fallback)
        self.assertNotIn("Battery review", [item.title for item in result.selected_items])

    def test_generate_report_attributes_the_source_funnel_to_one_canonical_duplicate(self) -> None:
        """A duplicate must contribute its post-dedup counters to one source only."""

        duplicate_from_arxiv = main.NewsItem(
            "Battery interface transport",
            "arXiv",
            datetime(2026, 7, 28, tzinfo=timezone.utc),
            "https://doi.org/10.1000/shared",
            abstract="Short record.",
            doi="10.1000/shared",
            source_id="arxiv",
        )
        canonical_pubmed_record = main.NewsItem(
            "Battery interface transport",
            "PubMed",
            datetime(2026, 7, 28, tzinfo=timezone.utc),
            "https://pubmed.ncbi.nlm.nih.gov/123/",
            abstract="A detailed battery interface transport study with reproducible methods." * 3,
            doi="10.1000/shared",
            authors=["A. Researcher", "B. Researcher"],
            source_id="pubmed",
        )
        europe_pmc_record = main.NewsItem(
            "Solid electrolyte stability",
            "Europe PMC",
            datetime(2026, 7, 28, tzinfo=timezone.utc),
            "https://europepmc.org/article/MED/456",
            abstract="A separate study about solid electrolyte stability.",
            source_id="europe_pmc",
        )
        items = [duplicate_from_arxiv, canonical_pubmed_record, europe_pmc_record]
        statuses = [
            main.source_status("arXiv", True, "arxiv", item_count=1),
            main.source_status("PubMed", True, "pubmed", item_count=1),
            main.source_status("Europe PMC", True, "europe_pmc", item_count=1),
        ]
        options = main.ReportGenerationOptions(
            days=1,
            max_items=10,
            min_items=1,
            source_limit=10,
            max_ai_items=10,
            llm_provider="openai",
            model="",
            report_date=date(2026, 7, 28),
            output_dir=Path(self.tempdir.name),
            require_ai=False,
            no_openai=False,
        )
        output_path = Path(self.tempdir.name) / "report.docx"
        with (
            patch.object(main, "collect_items", return_value=(items, statuses)),
            patch("network_check.run_network_checks", return_value=type("Diagnostics", (), {"network_ok": True, "summary_lines": lambda self: []})()),
            patch.object(main, "generate_ai_summaries", return_value=main.fallback_report_payload(items, self.profile)),
            patch.object(main, "apply_ai_scientific_notation", return_value=False),
            patch.object(main, "create_document", return_value=output_path),
        ):
            result = main.generate_report(options, self.profile, item_filter=lambda _item: True)

        counters = {
            status.source_id: (status.item_count, status.matched_count, status.deduplicated_count, status.selected_count)
            for status in result.source_statuses
        }
        self.assertEqual(
            counters,
            {
                "arxiv": (1, 1, 0, 0),
                "pubmed": (1, 1, 1, 1),
                "europe_pmc": (1, 1, 1, 1),
            },
        )

    def test_send_report_email_uses_explicit_custom_recipient_without_profile_fallback(self) -> None:
        pdf_path = Path(self.tempdir.name) / "preview.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n")
        smtp = CapturingSmtp()
        environment = {
            "EMAIL_ENABLED": "true",
            "SMTP_HOST": "smtp.test",
            "SMTP_USERNAME": "sender@test",
            "SMTP_PASSWORD": "x",
            "SMTP_FROM": "sender@test",
            "SMTP_SECURITY": "ssl",
            "REPORT_EMAIL_TO": "wrong@test",
        }

        with patch.dict("os.environ", environment, clear=True), patch.object(
            main.smtplib, "SMTP_SSL", return_value=smtp
        ):
            sent = main.send_report_email(
                pdf_path,
                date(2026, 7, 28),
                self.profile,
                ai_generated=True,
                recipient_override=["client@test"],
            )

        self.assertTrue(sent)
        self.assertEqual(smtp.messages[0]["To"], "client@test")

    def test_personalised_smtp_transport_error_is_exposed_as_ambiguous(self) -> None:
        class BrokenSmtp(CapturingSmtp):
            def send_message(self, message):
                raise ConnectionError("connection closed after DATA")

        pdf_path = Path(self.tempdir.name) / "preview.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n")
        environment = {
            "EMAIL_ENABLED": "true",
            "SMTP_HOST": "smtp.test",
            "SMTP_USERNAME": "sender@test",
            "SMTP_PASSWORD": "x",
            "SMTP_FROM": "sender@test",
            "SMTP_SECURITY": "ssl",
        }
        with patch.dict("os.environ", environment, clear=True), patch.object(
            main.smtplib, "SMTP_SSL", return_value=BrokenSmtp()
        ):
            with self.assertRaises(main.EmailTransportUncertainError):
                main.send_report_email(
                    pdf_path,
                    date(2026, 7, 28),
                    self.profile,
                    ai_generated=True,
                    recipient_override=["client@test"],
                    raise_on_transport_error=True,
                )

    def test_personalised_smtp_login_rejection_is_retryable(self) -> None:
        class LoginRejectedSmtp(CapturingSmtp):
            def login(self, username: str, password: str) -> None:
                raise main.smtplib.SMTPAuthenticationError(535, b"authentication failed")

        pdf_path = Path(self.tempdir.name) / "preview.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n")
        environment = {
            "EMAIL_ENABLED": "true",
            "SMTP_HOST": "smtp.test",
            "SMTP_USERNAME": "sender@test",
            "SMTP_PASSWORD": "x",
            "SMTP_FROM": "sender@test",
            "SMTP_SECURITY": "ssl",
        }
        with patch.dict("os.environ", environment, clear=True), patch.object(
            main.smtplib, "SMTP_SSL", return_value=LoginRejectedSmtp()
        ):
            sent = main.send_report_email(
                pdf_path,
                date(2026, 7, 28),
                self.profile,
                ai_generated=True,
                recipient_override=["client@test"],
                raise_on_transport_error=True,
            )

        self.assertFalse(sent)
