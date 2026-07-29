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
from personalization.profile import compose_effective_profile, item_matches_research_profile


class PersonalizationModelTests(unittest.TestCase):
    def valid_profile(
        self, *, lookback_days: int = 3, ccf_conference_tiers: tuple[str, ...] = ("A", "B")
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
            llm_provider="openai",
            llm_model="gpt-5.4-mini",
            output_formats=("docx",),
            lookback_days=lookback_days,
            ccf_conference_tiers=ccf_conference_tiers,
        )

    def test_recommendation_request_requires_the_three_operator_inputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "research_topic is required"):
            RecommendationRequest.from_form("张三", "reader@example.com", "")

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

    def test_selected_sources_and_preference_change_only_the_effective_profile(self) -> None:
        profile = self.make_profile(
            source_ids=("pubmed",),
            journal_ids=("0002-7863",),
            content_preferences=("mechanism",),
        )

        effective = compose_effective_profile(profile, "usr_001")

        self.assertEqual(effective["enabled_source_ids"], ("pubmed",))
        self.assertEqual([journal["source"] for journal in effective["crossref_journals"]], ["JACS"])
        self.assertIn("mechanism", effective["custom_preference_terms"])

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
