import os
import runpy
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

import dashboard.app as dashboard_app
from dashboard import views
import main
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

    def test_cached_local_repository_initializes_only_once_per_database_path(self) -> None:
        repository = unittest.mock.Mock()
        dashboard_app._open_repository.clear()
        try:
            with unittest.mock.patch.object(
                PersonalizationRepository, "for_sqlite", return_value=repository
            ) as open_sqlite:
                first = dashboard_app._open_repository("local", str(self.database_path), "")
                second = dashboard_app._open_repository("local", str(self.database_path), "")
        finally:
            dashboard_app._open_repository.clear()

        self.assertIs(first, second)
        open_sqlite.assert_called_once_with(self.database_path)
        repository.initialize.assert_called_once_with()

    def test_new_replica_does_not_contact_turso_until_manual_sync(self) -> None:
        replica_path = Path(self.tempdir.name) / "replica.db"
        repository = unittest.mock.Mock()
        dashboard_app._open_repository.clear()
        try:
            with unittest.mock.patch.object(
                PersonalizationRepository, "for_local_replica", return_value=repository
            ):
                opened = dashboard_app._open_repository(
                    "replica", str(replica_path), "libsql://dashboard.example"
                )
        finally:
            dashboard_app._open_repository.clear()

        self.assertIs(opened, repository)
        repository.initialize.assert_not_called()
        repository.sync.assert_not_called()

    def test_replica_mode_exposes_a_manual_sync_button(self) -> None:
        replica_path = Path(self.tempdir.name) / "replica.db"
        repository = mock.Mock()
        repository.is_local_replica = True
        repository.is_local_data_ready = True
        repository.last_sync_at = None
        repository.last_sync_error = None
        repository.operations_snapshot.return_value = {
            "total_users": 0,
            "pending": 0,
            "sent": 0,
            "retryable_failed": 0,
        }
        repository.list_recent_events.return_value = []
        repository.list_users.return_value = []
        dashboard_app._open_repository.clear()
        try:
            with (
                patch.dict(
                    os.environ,
                    {
                        "PERSONAL_ADMIN_LOCAL_DB": "",
                        "PERSONAL_ADMIN_REPLICA_PATH": str(replica_path),
                        "TURSO_DATABASE_URL": "libsql://dashboard.example",
                        "TURSO_AUTH_TOKEN": "test-token",
                    },
                    clear=False,
                ),
                patch.object(
                    PersonalizationRepository, "for_local_replica", return_value=repository
                ),
            ):
                app = AppTest.from_file(
                    str(Path(__file__).resolve().parents[1] / "dashboard/app.py")
                )
                app.run()
        finally:
            dashboard_app._open_repository.clear()

        self.assertIn("同步当前状态", [element.label for element in app.button])

    def test_manual_sync_button_calls_sync_only_after_the_user_clicks(self) -> None:
        replica_path = Path(self.tempdir.name) / "replica.db"
        repository = mock.Mock()
        repository.is_local_replica = True
        repository.is_local_data_ready = True
        repository.last_sync_at = None
        repository.last_sync_error = None
        repository.operations_snapshot.return_value = {
            "total_users": 0,
            "pending": 0,
            "sent": 0,
            "retryable_failed": 0,
        }
        repository.list_recent_events.return_value = []
        repository.list_users.return_value = []
        dashboard_app._open_repository.clear()
        try:
            with (
                patch.dict(
                    os.environ,
                    {
                        "PERSONAL_ADMIN_LOCAL_DB": "",
                        "PERSONAL_ADMIN_REPLICA_PATH": str(replica_path),
                        "TURSO_DATABASE_URL": "libsql://dashboard.example",
                        "TURSO_AUTH_TOKEN": "test-token",
                    },
                    clear=False,
                ),
                patch.object(
                    PersonalizationRepository, "for_local_replica", return_value=repository
                ),
            ):
                app = AppTest.from_file(
                    str(Path(__file__).resolve().parents[1] / "dashboard/app.py")
                )
                app.run()
                sync_button = next(button for button in app.button if button.label == "同步当前状态")
                sync_button.click().run()
        finally:
            dashboard_app._open_repository.clear()

        repository.sync.assert_called_once_with()
        self.assertIn("已同步当前状态", " ".join(element.value for element in app.success))

    def test_replica_without_a_completed_sync_shows_a_retryable_empty_state(self) -> None:
        replica_path = Path(self.tempdir.name) / "replica.db"
        repository = mock.Mock()
        repository.is_local_replica = True
        repository.is_local_data_ready = False
        repository.last_sync_at = None
        repository.last_sync_error = None
        dashboard_app._open_repository.clear()
        try:
            with (
                patch.dict(
                    os.environ,
                    {
                        "PERSONAL_ADMIN_LOCAL_DB": "",
                        "PERSONAL_ADMIN_REPLICA_PATH": str(replica_path),
                        "TURSO_DATABASE_URL": "libsql://dashboard.example",
                        "TURSO_AUTH_TOKEN": "test-token",
                    },
                    clear=False,
                ),
                patch.object(
                    PersonalizationRepository, "for_local_replica", return_value=repository
                ),
            ):
                app = AppTest.from_file(
                    str(Path(__file__).resolve().parents[1] / "dashboard/app.py")
                )
                app.run()
        finally:
            dashboard_app._open_repository.clear()

        rendered = " ".join(element.value for element in app.info)
        self.assertIn("本地副本尚未准备好", rendered)

    def test_replica_copy_does_not_claim_that_cloud_writes_are_pending_uploads(self) -> None:
        root = Path(__file__).resolve().parents[1]
        content = "\n".join(
            (root / path).read_text(encoding="utf-8")
            for path in ("README.md", "dashboard/app.py", "dashboard/views.py")
        )

        self.assertNotIn("本地修改尚未同步", content)
        self.assertNotIn("已保存在本地", content)
        self.assertIn("写入会直接提交到 Turso 云端主库", content)

    def test_secondary_buttons_keep_high_contrast_text(self) -> None:
        stylesheet = (Path(__file__).resolve().parents[1] / "dashboard/style.css").read_text(
            encoding="utf-8"
        )

        self.assertIn('.stButton > button:not([kind="primary"])', stylesheet)
        self.assertIn("color: var(--ink) !important;", stylesheet)

    def test_rendered_dashboard_injects_a_dark_system_theme(self) -> None:
        app = self.local_dashboard_app()

        styles = " ".join(
            markdown.value for markdown in app.markdown if "<style>" in markdown.value
        )

        self.assertIn("prefers-color-scheme: dark", styles)
        self.assertIn("--ink: #f5f5f7", styles)
        self.assertIn("--input-surface: #2c2c2e", styles)

    def test_user_page_requires_confirmation_before_permanent_deletion(self) -> None:
        self.create_preview_ready_user_with_disabled_schedule()
        app = self.local_dashboard_app()
        app.sidebar.radio[0].set_value("用户画像").run()

        delete_button = next(button for button in app.button if button.label == "删除用户")
        delete_button.click().run()

        button_labels = [button.label for button in app.button]
        warning_text = " ".join(element.value for element in app.warning)
        self.assertIn("确认永久删除", button_labels)
        self.assertIn("取消", button_labels)
        self.assertIn("画像、计划、预览和投递历史", warning_text)

        repository = PersonalizationRepository.for_sqlite(self.database_path)
        try:
            self.assertEqual([user.display_name for user in repository.list_users()], ["Alice"])
        finally:
            repository.close()

        cancel_button = next(button for button in app.button if button.label == "取消")
        cancel_button.click().run()
        self.assertNotIn("确认永久删除", [button.label for button in app.button])

        delete_button = next(button for button in app.button if button.label == "删除用户")
        delete_button.click().run()
        confirm_button = next(button for button in app.button if button.label == "确认永久删除")
        confirm_button.click().run()
        repository = PersonalizationRepository.for_sqlite(self.database_path)
        try:
            self.assertEqual(repository.list_users(), [])
        finally:
            repository.close()

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

    def test_user_profile_ui_explains_ai_description_and_new_source_layers(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "dashboard/views.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("用一段话描述用户想追踪的研究兴趣", source)
        self.assertEqual(views.BASE_PROFILE_LABELS, main.PROFILE_LABELS)
        self.assertEqual(views.SOURCE_LABELS["openalex"], "OpenAlex 学术索引")
        self.assertEqual(views.SOURCE_LABELS["hackernews"], "Hacker News 社区信号")
        self.assertEqual(views.SOURCE_LABELS["github_releases"], "GitHub Releases 社区信号")

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
