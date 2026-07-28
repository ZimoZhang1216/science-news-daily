import os
import runpy
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from personalization.models import ResearchProfileInput, ScheduleInput, UserInput
from personalization.repository import PersonalizationRepository


class DashboardSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.tempdir.name) / "dashboard.db"
        self.environment = patch.dict(
            os.environ, {"PERSONAL_ADMIN_LOCAL_DB": str(self.database_path)}, clear=False
        )
        self.environment.start()

    def tearDown(self) -> None:
        self.environment.stop()
        self.tempdir.cleanup()

    def local_dashboard_app(self) -> AppTest:
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "dashboard/app.py"))
        app.run()
        return app

    def create_preview_ready_user_with_disabled_schedule(self) -> None:
        repository = PersonalizationRepository.for_sqlite(self.database_path)
        repository.initialize()
        try:
            user_id = repository.create_user_with_profile(
                UserInput.from_form("Alice", "alice@example.test", "active"),
                ResearchProfileInput.from_form(
                    base_profile="chemistry",
                    research_topic="Lithium metal batteries",
                    include_keywords="battery",
                    exclude_keywords="",
                    source_ids=("arxiv",),
                    journal_ids=(),
                    content_preferences=("mechanism",),
                    max_items=12,
                    llm_provider="deepseek",
                    llm_model="deepseek-v4-flash",
                    output_formats=("docx", "pdf"),
                ),
                ScheduleInput.from_form("daily", None, "Asia/Shanghai", "07:30", False),
            )
            preview = repository.create_manual_preview(user_id, date(2026, 7, 28))
            self.assertIsNotNone(repository.claim_delivery(preview.delivery_id))
            repository.mark_preview_ready(
                preview.delivery_id, preview.report_run_id, "preview-artifact", "preview-run"
            )
        finally:
            repository.close()

    def test_entrypoint_imports_when_streamlit_executes_the_script_directly(self) -> None:
        root = Path(__file__).resolve().parents[1]
        dashboard_directory = root / "dashboard"
        original_path = sys.path[:]
        try:
            sys.path[:] = [
                str(dashboard_directory),
                *[
                    entry
                    for entry in original_path
                    if Path(entry or ".").resolve() != root
                ],
            ]
            module_globals = runpy.run_path(
                str(dashboard_directory / "app.py"),
                run_name="dashboard_entrypoint_test",
            )
        finally:
            sys.path[:] = original_path

        self.assertIn("PAGE_RENDERERS", module_globals)

    def test_missing_database_configuration_is_explained_without_secret_values(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "dashboard/app.py"))
            app.run()

        info_text = " ".join(element.value for element in app.info)
        self.assertIn("尚未配置 Turso", info_text)
        self.assertNotIn("TURSO_AUTH_TOKEN=", info_text)

    def test_user_page_exposes_mandatory_and_recommended_stages(self) -> None:
        app = self.local_dashboard_app()
        app.sidebar.radio[0].set_value("用户画像").run()

        rendered = " ".join(element.value for element in app.markdown)
        self.assertIn("必须填写", rendered)
        self.assertIn("生成建议", [element.label for element in app.button])

    def test_preview_ready_copy_never_offers_manual_email_send(self) -> None:
        self.create_preview_ready_user_with_disabled_schedule()
        app = self.local_dashboard_app()
        app.sidebar.radio[0].set_value("日报与投递").run()

        rendered = " ".join(element.value for element in app.markdown)
        button_labels = [element.label for element in app.button]
        legacy_manual_email_label = "确认并" + "发送"
        self.assertIn("启用固定频率计划", button_labels)
        self.assertNotIn(legacy_manual_email_label, rendered)
        self.assertNotIn(legacy_manual_email_label, button_labels)
        source = (Path(__file__).resolve().parents[1] / "dashboard/views.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn('dispatch_command(settings, "del' + 'iver"', source)

    def test_schedule_activation_copy_describes_the_next_automatic_email(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "dashboard/views.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("下一次自动发送日报", source)
        self.assertNotIn("下一次生成预览", source)
