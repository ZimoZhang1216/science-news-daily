import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import main
from personalization.models import RecommendationRequest
from personalization.recommender import RecommendationError, recommend_profile


def valid_request() -> RecommendationRequest:
    return RecommendationRequest.from_form(
        "张三", "reader@example.test", "固态电池界面与离子传导"
    )


def valid_response() -> dict[str, object]:
    return {
        "base_profile": "chemistry",
        "research_focus": "固态电池界面离子传导机制",
        "include_keywords": ["solid electrolyte", "SEI"],
        "exclude_keywords": ["editorial"],
        "source_ids": ["arxiv", "pubmed", "crossref"],
        "source_layer_ids": ["academic_research"],
        "journal_ids": ["1755-4330"],
        "content_preferences": ["mechanism", "methodology"],
        "max_items": 15,
        "output_formats": ["docx", "pdf"],
        "frequency": "daily",
        "weekday": None,
        "timezone": "Asia/Shanghai",
        "local_send_time": "07:30",
        "rationale": "课题强调固态电池界面与离子传导。",
        "uncertainty": "未给出目标期刊层级。",
    }


def invalid_journal_response() -> dict[str, object]:
    response = valid_response()
    response["journal_ids"] = ["0000-0000"]
    return response


def shared_social_source_response() -> dict[str, object]:
    response = valid_response()
    response["source_ids"] = ["hackernews"]
    return response


def restricted_source_response() -> dict[str, object]:
    response = valid_response()
    response["source_ids"] = ["openalex"]
    return response


def computer_science_response() -> dict[str, object]:
    response = valid_response()
    response.update(
        {
            "base_profile": "computer_science",
            "include_keywords": ["data cleaning", "AI agent"],
            "source_ids": ["arxiv", "ccf_conferences"],
            "journal_ids": ["0360-0300"],
            "rationale": "描述同时关注数据质量与 AI 智能体，因此选择计算机科学及其公开信号源。",
        }
    )
    return response


class PersonalizationRecommenderTests(unittest.TestCase):
    def test_recommender_uses_the_configured_provider_and_returns_editable_defaults(self) -> None:
        config = main.LLMConfig(
            provider="deepseek",
            model="deepseek-v4-flash",
            api_key="",
            api_key_env="DEEPSEEK_API_KEY",
            base_url="https://api.deepseek.com",
        )

        with patch.object(main, "resolve_llm_config", return_value=config):
            recommendation = recommend_profile(valid_request(), request_json=lambda *_: valid_response())

        self.assertEqual(recommendation.profile.llm_provider, "deepseek")
        self.assertEqual(recommendation.profile.llm_model, "deepseek-v4-flash")
        self.assertEqual(recommendation.profile.research_topic, "固态电池界面离子传导机制")
        self.assertNotEqual(recommendation.profile.research_topic, valid_request().research_topic)
        self.assertEqual(recommendation.profile.lookback_days, 3)
        self.assertFalse(recommendation.schedule.enabled)

    def test_recommender_rejects_a_journal_outside_the_selected_profile(self) -> None:
        config = main.LLMConfig("deepseek", "deepseek-v4-flash", "", "DEEPSEEK_API_KEY")

        with patch.object(main, "resolve_llm_config", return_value=config):
            with self.assertRaisesRegex(RecommendationError, "journal_ids"):
                recommend_profile(valid_request(), request_json=lambda *_: invalid_journal_response())

    def test_recommender_rejects_a_community_signal_from_automatic_recommendations(self) -> None:
        config = main.LLMConfig("deepseek", "deepseek-v4-flash", "", "DEEPSEEK_API_KEY")

        with patch.object(main, "resolve_llm_config", return_value=config):
            with self.assertRaisesRegex(RecommendationError, "source_ids"):
                recommend_profile(valid_request(), request_json=lambda *_: shared_social_source_response())

    def test_recommender_rejects_an_authorised_or_non_default_catalogue_source(self) -> None:
        config = main.LLMConfig("deepseek", "deepseek-v4-flash", "", "DEEPSEEK_API_KEY")

        with patch.object(main, "resolve_llm_config", return_value=config):
            with self.assertRaisesRegex(RecommendationError, "source_ids"):
                recommend_profile(valid_request(), request_json=lambda *_: restricted_source_response())

    def test_recommender_rejects_a_community_layer_from_automatic_recommendations(self) -> None:
        config = main.LLMConfig("deepseek", "deepseek-v4-flash", "", "DEEPSEEK_API_KEY")
        response = valid_response()
        response["source_layer_ids"] = ["community_signal"]

        with patch.object(main, "resolve_llm_config", return_value=config):
            with self.assertRaisesRegex(RecommendationError, "source_layer_ids"):
                recommend_profile(valid_request(), request_json=lambda *_: response)

    def test_recommender_uses_profile_specific_source_catalogue_for_a_free_text_description(self) -> None:
        config = main.LLMConfig("deepseek", "deepseek-v4-flash", "", "DEEPSEEK_API_KEY")
        captured_prompt: dict[str, object] = {}

        def respond(_instructions: str, prompt: str) -> dict[str, object]:
            captured_prompt.update(json.loads(prompt))
            return computer_science_response()

        request = RecommendationRequest.from_form(
            "李四",
            "reader@example.test",
            "我想追踪数据清洗、数据修复、时空数据，以及 AI agent 和开源工具的进展。",
        )
        with patch.object(main, "resolve_llm_config", return_value=config):
            recommendation = recommend_profile(request, request_json=respond)

        self.assertEqual(recommendation.profile.base_profile, "computer_science")
        self.assertEqual(
            recommendation.profile.source_ids,
            ("arxiv", "ccf_conferences"),
        )
        self.assertEqual(recommendation.profile.source_layer_ids, ("academic_research",))
        self.assertEqual(recommendation.profile.ccf_conference_tiers, ("A", "B"))
        source_catalogue = captured_prompt["supported_source_ids_by_profile"]
        self.assertEqual(
            source_catalogue["computer_science"],
            ["arxiv", "crossref", "rss", "ccf_conferences", "official_rss"],
        )

    def test_recommender_accepts_a_legacy_response_without_source_layer_ids(self) -> None:
        config = main.LLMConfig("deepseek", "deepseek-v4-flash", "", "DEEPSEEK_API_KEY")
        response = valid_response()
        response.pop("source_layer_ids")

        with patch.object(main, "resolve_llm_config", return_value=config):
            recommendation = recommend_profile(valid_request(), request_json=lambda *_: response)

        self.assertEqual(recommendation.profile.source_layer_ids, ())

    def test_recommender_retries_without_json_mode_when_compatible_endpoint_rejects_it(self) -> None:
        config = main.LLMConfig(
            "deepseek",
            "deepseek-v4-flash",
            "test-key",
            "DEEPSEEK_API_KEY",
            "https://api.deepseek.com",
        )
        requests: list[dict[str, object]] = []

        def create(**kwargs: object) -> object:
            requests.append(kwargs)
            if "response_format" in kwargs:
                raise RuntimeError("JSON mode is unsupported")
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(valid_response())))]
            )

        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with (
            patch.object(main, "resolve_llm_config", return_value=config),
            patch.object(main, "OpenAI", return_value=client),
        ):
            recommendation = recommend_profile(valid_request())

        self.assertEqual(recommendation.profile.base_profile, "chemistry")
        self.assertEqual(len(requests), 2)
        self.assertIn("response_format", requests[0])
        self.assertNotIn("response_format", requests[1])
