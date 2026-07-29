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


def computer_science_response() -> dict[str, object]:
    response = valid_response()
    response.update(
        {
            "base_profile": "computer_science",
            "include_keywords": ["data cleaning", "AI agent"],
            "source_ids": ["arxiv", "openalex", "hackernews", "github_releases"],
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
        self.assertFalse(recommendation.schedule.enabled)

    def test_recommender_rejects_a_journal_outside_the_selected_profile(self) -> None:
        config = main.LLMConfig("deepseek", "deepseek-v4-flash", "", "DEEPSEEK_API_KEY")

        with patch.object(main, "resolve_llm_config", return_value=config):
            with self.assertRaisesRegex(RecommendationError, "journal_ids"):
                recommend_profile(valid_request(), request_json=lambda *_: invalid_journal_response())

    def test_recommender_allows_a_shared_source_outside_the_base_profile_catalogue(self) -> None:
        config = main.LLMConfig("deepseek", "deepseek-v4-flash", "", "DEEPSEEK_API_KEY")

        with patch.object(main, "resolve_llm_config", return_value=config):
            try:
                recommendation = recommend_profile(
                    valid_request(), request_json=lambda *_: shared_social_source_response()
                )
            except RecommendationError:
                recommendation = None

        self.assertIsNotNone(recommendation)
        assert recommendation is not None
        self.assertEqual(recommendation.profile.source_ids, ("hackernews",))

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
            ("arxiv", "openalex", "hackernews", "github_releases"),
        )
        source_catalogue = captured_prompt["supported_source_ids_by_profile"]
        self.assertEqual(
            source_catalogue["computer_science"],
            list(main.available_source_ids("computer_science")),
        )

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
