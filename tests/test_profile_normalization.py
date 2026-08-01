import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import main
from personalization.models import RecommendationRequest, ResearchProfileInput, ScheduleInput, UserInput
from personalization.normalization import normalize_existing_profiles
from personalization.recommender import RecommendationError, recommend_profile
from personalization.repository import PersonalizationRepository


def _response(focus: str) -> dict[str, object]:
    return {
        "base_profile": "economics",
        "research_focus": focus,
        "include_keywords": ["macroeconomics", "financial markets"],
        "exclude_keywords": ["sports"],
        "source_ids": ["arxiv"],
        "source_layer_ids": ["academic_research"],
        "journal_ids": [],
        "content_preferences": ["methodology"],
        "max_items": 12,
        "output_formats": ["docx", "pdf"],
        "frequency": "daily",
        "weekday": None,
        "timezone": "Asia/Shanghai",
        "local_send_time": "08:00",
        "rationale": "聚焦经济研究与市场动态。",
        "uncertainty": "未提供特定期刊名单。",
    }


class ProfileNormalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repository = PersonalizationRepository.for_sqlite(Path(self.tempdir.name) / "profiles.db")
        self.repository.initialize()
        self.config = main.LLMConfig("deepseek", "deepseek-v4-flash", "", "DEEPSEEK_API_KEY")

    def tearDown(self) -> None:
        self.repository.close()
        self.tempdir.cleanup()

    def _user(self, name: str, topic: str) -> str:
        return self.repository.create_user_with_profile(
            UserInput.from_form(name, f"{name.lower()}@example.test", "active"),
            ResearchProfileInput.from_form(
                base_profile="economics",
                research_topic=topic,
                include_keywords="economy",
                exclude_keywords="",
                source_ids=("arxiv",),
                journal_ids=(),
                content_preferences=("review",),
                max_items=10,
                llm_provider="deepseek",
                llm_model="deepseek-v4-flash",
                output_formats=("docx", "pdf"),
            ),
            ScheduleInput.from_form("weekly", 2, "Asia/Shanghai", "08:00", True),
        )

    def test_normalizing_existing_profiles_creates_concise_current_versions_without_changing_schedules(self) -> None:
        first = self._user(
            "Alice", "偏好：宏观数据、金融资讯与国际贸易；信息来源：机构报告和权威媒体。"
        )
        second = self._user("Bob", "关注经济增长、市场政策与产业动态。")
        before = self.repository.get_schedule(first)

        def recommender(request: RecommendationRequest):
            focus = "宏观经济、金融市场与国际贸易" if request.display_name == "Alice" else "经济增长、政策与产业动态"
            with patch.object(main, "resolve_llm_config", return_value=self.config):
                return recommend_profile(request, request_json=lambda *_: _response(focus))

        summary = normalize_existing_profiles(self.repository, recommender=recommender)

        first_current = self.repository.get_current_profile(first)
        second_current = self.repository.get_current_profile(second)
        after = self.repository.get_schedule(first)
        self.assertEqual(summary.normalized, 2)
        self.assertEqual(summary.failed, 0)
        self.assertEqual(first_current.version, 2)
        self.assertEqual(first_current.input.research_topic, "宏观经济、金融市场与国际贸易")
        self.assertEqual(second_current.input.research_topic, "经济增长、政策与产业动态")
        self.assertEqual(len(self.repository.list_profile_versions(first)), 2)
        self.assertEqual(first_current.input.source_layer_ids, ("academic_research",))
        self.assertEqual(after.frequency, before.frequency)
        self.assertEqual(after.weekday, before.weekday)
        self.assertEqual(after.timezone, before.timezone)
        self.assertEqual(after.local_send_time, before.local_send_time)
        self.assertTrue(after.enabled)

    def test_one_recommendation_failure_does_not_revert_other_user_normalization(self) -> None:
        successful = self._user("Alice", "宏观经济与金融市场")
        failed = self._user("Bob", "产业政策与贸易")

        def recommender(request: RecommendationRequest):
            if request.display_name == "Bob":
                raise RecommendationError("model unavailable")
            with patch.object(main, "resolve_llm_config", return_value=self.config):
                return recommend_profile(
                    request, request_json=lambda *_: _response("宏观经济与金融市场研究")
                )

        summary = normalize_existing_profiles(self.repository, recommender=recommender)

        self.assertEqual(summary.normalized, 1)
        self.assertEqual(summary.failed, 1)
        self.assertEqual(self.repository.get_current_profile(successful).version, 2)
        self.assertEqual(self.repository.get_current_profile(failed).version, 1)

    def test_normalizing_a_legacy_model_response_without_layers_creates_one_compatible_version(self) -> None:
        user_id = self._user("Alice", "宏观经济与金融市场")

        def recommender(request: RecommendationRequest):
            response = _response("宏观经济与金融市场研究")
            response.pop("source_layer_ids")
            with patch.object(main, "resolve_llm_config", return_value=self.config):
                return recommend_profile(request, request_json=lambda *_: response)

        summary = normalize_existing_profiles(self.repository, recommender=recommender)

        current = self.repository.get_current_profile(user_id)
        self.assertEqual(summary.as_dict(), {"total": 1, "normalized": 1, "failed": 0})
        self.assertEqual(current.version, 2)
        self.assertEqual(current.input.source_layer_ids, ())


if __name__ == "__main__":
    unittest.main()
