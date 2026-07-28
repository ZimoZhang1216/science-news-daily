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
        self.assertFalse(recommendation.schedule.enabled)

    def test_recommender_rejects_a_journal_outside_the_selected_profile(self) -> None:
        config = main.LLMConfig("deepseek", "deepseek-v4-flash", "", "DEEPSEEK_API_KEY")

        with patch.object(main, "resolve_llm_config", return_value=config):
            with self.assertRaisesRegex(RecommendationError, "journal_ids"):
                recommend_profile(valid_request(), request_json=lambda *_: invalid_journal_response())

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
