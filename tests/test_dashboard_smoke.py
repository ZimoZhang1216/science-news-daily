import os
import runpy
import sys
import tempfile
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
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

    def create_user(
        self,
        status: str = "active",
        llm_provider: str = "deepseek",
        llm_model: str = "deepseek-v4-flash",
        source_ids: tuple[str, ...] = ("arxiv",),
        base_profile: str = "chemistry",
    ) -> str:
        repository = PersonalizationRepository.for_sqlite(self.database_path)
        repository.initialize()
        try:
            return repository.create_user_with_profile(
                UserInput.from_form("Alice", "alice@example.test", status),
                ResearchProfileInput.from_form(
                    base_profile=base_profile,
                    research_topic="Lithium metal batteries",
                    include_keywords="battery",
                    exclude_keywords="",
                    source_ids=source_ids,
                    journal_ids=(),
                    content_preferences=("mechanism",),
                    max_items=12,
                    llm_provider=llm_provider,
                    llm_model=llm_model,
                    output_formats=("docx", "pdf"),
                ),
                ScheduleInput.from_form("daily", None, "Asia/Shanghai", "07:30", False),
            )
        finally:
            repository.close()

    def create_preview_ready_user_with_disabled_schedule(self) -> None:
        repository = PersonalizationRepository.for_sqlite(self.database_path)
        repository.initialize()
        try:
            user_id = self.create_user()
            preview = repository.create_manual_preview(user_id, date(2026, 7, 28))
            self.assertIsNotNone(repository.claim_delivery(preview.delivery_id))
            repository.mark_preview_ready(
                preview.delivery_id, preview.report_run_id, "preview-artifact", "preview-run"
            )
        finally:
            repository.close()

    def create_queued_preview(self) -> str:
        repository = PersonalizationRepository.for_sqlite(self.database_path)
        repository.initialize()
        try:
            user_id = self.create_user()
            return repository.create_manual_preview(user_id, date(2026, 7, 28)).delivery_id
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

    def test_user_profile_forms_expose_constrained_ccf_tier_selection_for_computer_science(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "dashboard" / "views.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('"CCF 会议等级"', source)
        self.assertIn('"A + B + C"', source)
        self.assertIn('base_profile == "computer_science"', source)
        self.assertIn('current.base_profile == "computer_science"', source)

    def test_legacy_cached_profile_uses_the_default_candidate_budget(self) -> None:
        self.assertEqual(views._candidate_limit_for_form(SimpleNamespace()), 300)

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

    def test_terminate_button_cancels_a_queued_delivery(self) -> None:
        delivery_id = self.create_queued_preview()
        dashboard_app._open_repository.clear()
        try:
            app = self.local_dashboard_app()
            navigation = next(radio for radio in app.radio if radio.label == "功能导航")
            navigation.set_value("日报与投递").run()
            terminate = next(button for button in app.button if button.label == "终止任务")
            terminate.click().run()
        finally:
            dashboard_app._open_repository.clear()

        repository = PersonalizationRepository.for_sqlite(self.database_path)
        try:
            self.assertEqual(repository.get_delivery(delivery_id).status, "cancelled")
        finally:
            repository.close()

    def test_delivery_page_renders_task_scoped_source_metrics(self) -> None:
        delivery_id = self.create_queued_preview()
        repository = PersonalizationRepository.for_sqlite(self.database_path)
        try:
            delivery = repository.get_delivery(delivery_id)
            repository.record_generation_metrics(
                delivery.report_run_id,
                collected_count=8,
                matched_count=6,
                deduplicated_count=5,
                history_excluded_count=1,
                selected_count=4,
                ai_generated=True,
                profile_filter_fallback=False,
                source_statuses=[
                    main.SourceStatus(
                        "arXiv", True, 8, source_id="arxiv",
                        source_layer="academic_research", credibility=3,
                        matched_count=6, deduplicated_count=5, selected_count=4,
                    )
                ],
            )
        finally:
            repository.close()

        dashboard_app._open_repository.clear()
        try:
            app = self.local_dashboard_app()
            app.sidebar.radio[0].set_value("日报与投递").run()
        finally:
            dashboard_app._open_repository.clear()

        self.assertIn("任务详情", [expander.label for expander in app.expander])
        self.assertIn("抓取原始条目", [metric.label for metric in app.metric])
        rendered = "\n".join(dataframe.value.to_string() for dataframe in app.dataframe)
        self.assertIn("arXiv", rendered)
        self.assertIn("来源类型", rendered)
        self.assertIn("最终入选", rendered)

    def test_profile_source_controls_explain_layers_and_restricted_catalogue_entries(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "dashboard" / "views.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("可信信源层级", source)
        self.assertIn("目录收录、尚未接入", source)
        self.assertIn("需要授权", source)
        self.assertIn("source_layer_ids=source_layer_ids", source)

    def test_openrouter_profile_opens_the_source_selection_form(self) -> None:
        self.create_user(llm_provider="openrouter", llm_model="deepseek/deepseek-chat")

        app = self.local_dashboard_app()
        app.sidebar.radio[0].set_value("用户画像").run()

        provider = next(box for box in app.selectbox if box.label == "模型服务商")
        self.assertEqual(provider.value, "openrouter")
        self.assertIn("可信信源层级", [box.label for box in app.multiselect])

    def test_legacy_directory_source_is_retained_in_the_edit_form(self) -> None:
        self.create_user(
            base_profile="economics",
            source_ids=("international_statistics",),
        )

        app = self.local_dashboard_app()
        app.sidebar.radio[0].set_value("用户画像").run()

        self.assertIn("已有但暂未接入的来源", [box.label for box in app.multiselect])

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

    def test_user_page_offers_ai_normalization_for_legacy_profiles(self) -> None:
        self.create_queued_preview()
        app = self.local_dashboard_app()
        app.sidebar.radio[0].set_value("用户画像").run()

        self.assertIn("用 AI 统一优化已有用户", [element.label for element in app.button])

    def test_user_profile_ui_explains_ai_description_and_new_source_layers(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "dashboard/views.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("用一段话描述用户想追踪的研究兴趣", source)
        self.assertEqual(views.BASE_PROFILE_LABELS, main.PROFILE_LABELS)
        self.assertEqual(views.SOURCE_LABELS["openalex"], "OpenAlex 学术索引")
        self.assertEqual(views.SOURCE_LABELS["hackernews"], "Hacker News 社区信号")
        self.assertEqual(views.SOURCE_LABELS["github_releases"], "GitHub Releases 社区信号")

    def test_user_profile_ui_exposes_a_one_to_sixty_day_information_window(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "dashboard/views.py").read_text(
            encoding="utf-8"
        )

        self.assertEqual(source.count('"资讯时间窗口（天）"'), 2)
        self.assertIn("min_value=1", source)
        self.assertIn("max_value=60", source)

    def test_active_user_manual_send_requires_safe_confirmation_before_dispatch(self) -> None:
        user_id = self.create_user()
        dashboard_app._open_repository.clear()
        try:
            with (
                patch.dict(
                    os.environ,
                    {
                        "PERSONAL_ADMIN_GITHUB_REPOSITORY": "owner/repo",
                        "GITHUB_DISPATCH_TOKEN": "test-token",
                    },
                    clear=False,
                ),
                patch.object(views, "dispatch_command") as dispatch,
            ):
                app = self.local_dashboard_app()
                app.sidebar.radio[0].set_value("用户画像").run()

                send_button = next(
                    button for button in app.button if button.label == "手动发报"
                )
                send_button.click().run()

                self.assertEqual(
                    [element.value for element in app.warning],
                    ["确认立即生成一份新的 PDF 日报并通过邮件发送？"],
                )
                self.assertIn(
                    "确认立即发送", [button.label for button in app.button]
                )
                dispatch.assert_not_called()

                repository = PersonalizationRepository.for_sqlite(self.database_path)
                try:
                    self.assertFalse(
                        any(
                            delivery["user_id"] == user_id
                            for delivery in repository.list_recent_deliveries()
                        )
                    )
                finally:
                    repository.close()

                confirm = next(
                    button
                    for button in app.button
                    if button.label == "确认立即发送"
                )
                confirm.click().run()
        finally:
            dashboard_app._open_repository.clear()

        dispatch.assert_called_once()
        settings, command, delivery_id = dispatch.call_args.args
        self.assertEqual(settings.repository, "owner/repo")
        self.assertEqual(command, "deliver")
        self.assertTrue(delivery_id.startswith("dlv_"))

    def test_paused_user_does_not_offer_manual_send(self) -> None:
        self.create_user(status="paused")
        app = self.local_dashboard_app()
        app.sidebar.radio[0].set_value("用户画像").run()

        self.assertNotIn("手动发报", [button.label for button in app.button])

    def test_existing_nonqueued_manual_send_shows_status_without_redispatch(self) -> None:
        user_id = self.create_user()
        repository = PersonalizationRepository.for_sqlite(self.database_path)
        try:
            existing = repository.create_manual_send(user_id, datetime.now(UTC))
            self.assertIsNotNone(
                repository.claim_queued_manual_send(existing.delivery_id)
            )
        finally:
            repository.close()

        dashboard_app._open_repository.clear()
        try:
            with (
                patch.dict(
                    os.environ,
                    {
                        "PERSONAL_ADMIN_GITHUB_REPOSITORY": "owner/repo",
                        "GITHUB_DISPATCH_TOKEN": "test-token",
                    },
                    clear=False,
                ),
                patch.object(views, "dispatch_command") as dispatch,
            ):
                app = self.local_dashboard_app()
                app.sidebar.radio[0].set_value("用户画像").run()
                next(
                    button for button in app.button if button.label == "手动发报"
                ).click().run()
                next(
                    button
                    for button in app.button
                    if button.label == "确认立即发送"
                ).click().run()
        finally:
            dashboard_app._open_repository.clear()

        dispatch.assert_not_called()
        status_text = " ".join(
            [element.value for element in app.info]
            + [element.value for element in app.warning]
            + [element.value for element in app.success]
        )
        self.assertIn("今日手动发报任务已存在", status_text)
        self.assertIn(views.DELIVERY_STATUS_LABELS["claimed"], status_text)

    def test_dispatch_failure_can_redispatch_the_same_queued_manual_send(self) -> None:
        user_id = self.create_user()
        dashboard_app._open_repository.clear()
        try:
            with (
                patch.dict(
                    os.environ,
                    {
                        "PERSONAL_ADMIN_GITHUB_REPOSITORY": "owner/repo",
                        "GITHUB_DISPATCH_TOKEN": "test-token",
                    },
                    clear=False,
                ),
                patch.object(
                    views,
                    "dispatch_command",
                    side_effect=[RuntimeError("unavailable"), None],
                ) as dispatch,
            ):
                app = self.local_dashboard_app()
                app.sidebar.radio[0].set_value("用户画像").run()
                next(
                    button for button in app.button if button.label == "手动发报"
                ).click().run()
                next(
                    button
                    for button in app.button
                    if button.label == "确认立即发送"
                ).click().run()
                next(
                    button for button in app.button if button.label == "手动发报"
                ).click().run()
                next(
                    button
                    for button in app.button
                    if button.label == "确认立即发送"
                ).click().run()
        finally:
            dashboard_app._open_repository.clear()

        self.assertEqual(dispatch.call_count, 2)
        delivery_ids = [call.args[2] for call in dispatch.call_args_list]
        self.assertEqual(delivery_ids[0], delivery_ids[1])
        repository = PersonalizationRepository.for_sqlite(self.database_path)
        try:
            deliveries = repository.list_deliveries_for_user(user_id)
        finally:
            repository.close()
        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0].status, "queued")
        self.assertEqual(deliveries[0].attempt_count, 0)

    def test_missing_settings_can_dispatch_the_existing_queued_manual_send_later(self) -> None:
        user_id = self.create_user()
        dashboard_app._open_repository.clear()
        try:
            with (
                patch.dict(
                    os.environ,
                    {
                        "PERSONAL_ADMIN_GITHUB_REPOSITORY": "",
                        "GITHUB_DISPATCH_TOKEN": "",
                    },
                    clear=False,
                ),
                patch.object(views, "dispatch_command") as dispatch,
            ):
                app = self.local_dashboard_app()
                app.sidebar.radio[0].set_value("用户画像").run()
                next(
                    button for button in app.button if button.label == "手动发报"
                ).click().run()
                next(
                    button
                    for button in app.button
                    if button.label == "确认立即发送"
                ).click().run()
                os.environ["PERSONAL_ADMIN_GITHUB_REPOSITORY"] = "owner/repo"
                os.environ["GITHUB_DISPATCH_TOKEN"] = "test-token"
                next(
                    button for button in app.button if button.label == "手动发报"
                ).click().run()
                next(
                    button
                    for button in app.button
                    if button.label == "确认立即发送"
                ).click().run()
        finally:
            dashboard_app._open_repository.clear()

        dispatch.assert_called_once()
        repository = PersonalizationRepository.for_sqlite(self.database_path)
        try:
            deliveries = repository.list_deliveries_for_user(user_id)
        finally:
            repository.close()
        self.assertEqual(len(deliveries), 1)
        self.assertEqual(dispatch.call_args.args[2], deliveries[0].id)
        self.assertEqual(deliveries[0].status, "queued")
        self.assertEqual(deliveries[0].attempt_count, 0)

    def test_schedule_activation_copy_describes_the_next_automatic_email(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "dashboard/views.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("下一次自动发送日报", source)
        self.assertNotIn("下一次生成预览", source)
