import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import main
from personalization.models import ResearchProfileInput, ScheduleInput, UserInput
from personalization.repository import PersonalizationRepository


class PersonalizationRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repository = PersonalizationRepository.for_sqlite(
            Path(self.tempdir.name) / "admin.db"
        )
        self.repository.initialize()

    def tearDown(self) -> None:
        self.repository.close()
        self.tempdir.cleanup()

    def user(self) -> UserInput:
        return UserInput.from_form("Alice", "alice@example.test", "active")

    def profile(
        self,
        keyword: str,
        *,
        lookback_days: int = 3,
        ccf_conference_tiers: tuple[str, ...] = ("A", "B"),
        source_layer_ids: tuple[str, ...] = (),
    ) -> ResearchProfileInput:
        return ResearchProfileInput.from_form(
            base_profile="chemistry",
            research_topic="Lithium metal batteries",
            include_keywords=keyword,
            exclude_keywords="",
            source_ids=("arxiv",),
            journal_ids=(),
            content_preferences=("mechanism",),
            max_items=12,
            llm_provider="openai",
            llm_model="gpt-5.4-mini",
            output_formats=("docx", "pdf"),
            lookback_days=lookback_days,
            ccf_conference_tiers=ccf_conference_tiers,
            source_layer_ids=source_layer_ids,
        )

    def daily_schedule(self) -> ScheduleInput:
        return ScheduleInput.from_form("daily", None, "Asia/Shanghai", "07:30", True)

    def disabled_daily_schedule(self) -> ScheduleInput:
        return ScheduleInput.from_form("daily", None, "Asia/Shanghai", "07:30", False)

    def create_user_and_mark_preview_ready(self, schedule_enabled: bool) -> tuple[str, str]:
        schedule = self.daily_schedule() if schedule_enabled else self.disabled_daily_schedule()
        user_id = self.repository.create_user_with_profile(self.user(), self.profile("battery"), schedule)
        preview = self.repository.create_manual_preview(user_id, date(2026, 7, 28))
        self.assertIsNotNone(self.repository.claim_delivery(preview.delivery_id))
        self.repository.mark_preview_ready(
            preview.delivery_id,
            preview.report_run_id,
            "preview-artifact",
            "preview-run",
        )
        return user_id, preview.delivery_id

    def test_profile_saves_an_immutable_new_version(self) -> None:
        user_id = self.repository.create_user_with_profile(
            self.user(),
            self.profile("battery", source_layer_ids=("academic_research",)),
            self.daily_schedule(),
        )

        version_two = self.repository.save_profile_version(
            user_id,
            self.profile(
                "solid electrolyte",
                lookback_days=60,
                source_layer_ids=("official_data_policy",),
            ),
        )
        current = self.repository.get_current_profile(user_id)
        versions = self.repository.list_profile_versions(user_id)

        self.assertEqual(version_two, 2)
        self.assertEqual(current.version, 2)
        self.assertEqual(versions[0].include_keywords, ("battery",))
        self.assertEqual(versions[1].include_keywords, ("solid electrolyte",))
        self.assertEqual(versions[0].input.lookback_days, 3)
        self.assertEqual(current.input.lookback_days, 60)
        self.assertEqual(current.input.ccf_conference_tiers, ("A", "B"))
        self.assertEqual(versions[0].input.source_layer_ids, ("academic_research",))
        self.assertEqual(current.input.source_layer_ids, ("official_data_policy",))

    def test_profile_versions_round_trip_the_ccf_tier_scope(self) -> None:
        user_id = self.repository.create_user_with_profile(
            self.user(), self.profile("battery", ccf_conference_tiers=("A", "B", "C")), self.daily_schedule()
        )

        current = self.repository.get_current_profile(user_id)

        self.assertEqual(current.input.ccf_conference_tiers, ("A", "B", "C"))

    def test_profile_versions_round_trip_source_layer_ids_as_json(self) -> None:
        user_id = self.repository.create_user_with_profile(
            self.user(),
            self.profile(
                "battery",
                source_layer_ids=("academic_research", "official_data_policy"),
            ),
            self.daily_schedule(),
        )

        row = self.repository._fetchone(
            "SELECT source_layer_ids_json FROM research_profiles WHERE user_id = ? AND is_current = 1",
            (user_id,),
        )
        current = self.repository.get_current_profile(user_id)

        self.assertEqual(
            json.loads(self.repository._value(row, "source_layer_ids_json")),
            ["academic_research", "official_data_policy"],
        )
        self.assertEqual(
            current.input.source_layer_ids,
            ("academic_research", "official_data_policy"),
        )

    def test_initialize_adds_three_day_lookback_default_to_a_legacy_schema(self) -> None:
        legacy_path = Path(self.tempdir.name) / "legacy.db"
        legacy_schema = (Path(__file__).resolve().parents[1] / "personalization/schema.sql").read_text(
            encoding="utf-8"
        ).replace("    lookback_days INTEGER NOT NULL DEFAULT 3,\n", "").replace(
            "    ccf_conference_tiers_json TEXT NOT NULL DEFAULT '[\"A\", \"B\"]',\n", ""
        ).replace(
            "    source_layer_ids_json TEXT NOT NULL DEFAULT '[]',\n", ""
        ).replace("    matched_count INTEGER NOT NULL DEFAULT 0,\n", "").replace(
            "    deduplicated_count INTEGER NOT NULL DEFAULT 0,\n", ""
        ).replace("    history_excluded_count INTEGER NOT NULL DEFAULT 0,\n", "").replace(
            "    profile_filter_fallback INTEGER NOT NULL DEFAULT 0,\n", ""
        ).replace("    metrics_recorded_at TEXT NOT NULL DEFAULT '',\n", "").replace(
            "    source_id TEXT NOT NULL DEFAULT '',\n", ""
        ).replace("    source_layer TEXT NOT NULL DEFAULT 'academic_research',\n", "").replace(
            "    credibility INTEGER NOT NULL DEFAULT 0,\n", ""
        ).replace(
            "    selected_count INTEGER NOT NULL DEFAULT 0,\n    error_summary TEXT NOT NULL DEFAULT '',\n",
            "    error_summary TEXT NOT NULL DEFAULT '',\n",
        )
        legacy_connection = sqlite3.connect(legacy_path)
        legacy_connection.executescript(legacy_schema)
        legacy_connection.close()

        legacy_repository = PersonalizationRepository.for_sqlite(legacy_path)
        try:
            legacy_repository.initialize()
            columns = legacy_repository._table_columns("research_profiles")
            self.assertIn("lookback_days", columns)
            self.assertIn("ccf_conference_tiers_json", columns)
            self.assertIn("source_layer_ids_json", columns)
            column = legacy_repository._fetchone(
                "SELECT dflt_value FROM pragma_table_info('research_profiles') WHERE name = 'lookback_days'"
            )
            self.assertEqual(str(legacy_repository._value(column, "dflt_value")).strip("'\""), "3")
            tier_column = legacy_repository._fetchone(
                "SELECT dflt_value FROM pragma_table_info('research_profiles') WHERE name = 'ccf_conference_tiers_json'"
            )
            self.assertEqual(
                str(legacy_repository._value(tier_column, "dflt_value")).strip("'\""),
                '["A", "B"]',
            )
            layer_column = legacy_repository._fetchone(
                "SELECT dflt_value FROM pragma_table_info('research_profiles') WHERE name = 'source_layer_ids_json'"
            )
            self.assertEqual(
                str(legacy_repository._value(layer_column, "dflt_value")).strip("'\""),
                "[]",
            )
            report_run_columns = legacy_repository._table_columns("report_runs")
            self.assertTrue(
                {
                    "matched_count",
                    "deduplicated_count",
                    "history_excluded_count",
                    "profile_filter_fallback",
                    "metrics_recorded_at",
                }.issubset(report_run_columns)
            )
            source_metric_columns = legacy_repository._table_columns("source_metrics")
            self.assertTrue(
                {
                    "source_id",
                    "source_layer",
                    "credibility",
                    "matched_count",
                    "deduplicated_count",
                    "selected_count",
                }.issubset(source_metric_columns)
            )
            user_id = legacy_repository.create_user_with_profile(
                self.user(), self.profile("battery"), self.daily_schedule()
            )
            delivery = legacy_repository.create_manual_preview(user_id, date(2026, 7, 28))
            metrics = legacy_repository.get_delivery_task_metrics(delivery.delivery_id)
            self.assertEqual(metrics["recorded_at"], "")
            self.assertEqual(metrics["sources"], [])
        finally:
            legacy_repository.close()

    def test_initialize_reads_a_real_pre_migration_profile_with_no_source_layers(self) -> None:
        legacy_path = Path(self.tempdir.name) / "pre-migration-profile.db"
        legacy_schema = (Path(__file__).resolve().parents[1] / "personalization/schema.sql").read_text(
            encoding="utf-8"
        ).replace("    lookback_days INTEGER NOT NULL DEFAULT 3,\n", "").replace(
            "    ccf_conference_tiers_json TEXT NOT NULL DEFAULT '[\"A\", \"B\"]',\n", ""
        ).replace("    source_layer_ids_json TEXT NOT NULL DEFAULT '[]',\n", "").replace(
            "    source_id TEXT NOT NULL DEFAULT '',\n", ""
        ).replace("    source_layer TEXT NOT NULL DEFAULT 'academic_research',\n", "").replace(
            "    credibility INTEGER NOT NULL DEFAULT 0,\n", ""
        ).replace("    matched_count INTEGER NOT NULL DEFAULT 0,\n", "").replace(
            "    deduplicated_count INTEGER NOT NULL DEFAULT 0,\n", ""
        ).replace(
            "    selected_count INTEGER NOT NULL DEFAULT 0,\n    error_summary TEXT NOT NULL DEFAULT '',\n",
            "    error_summary TEXT NOT NULL DEFAULT '',\n",
        )
        connection = sqlite3.connect(legacy_path)
        try:
            connection.executescript(legacy_schema)
            connection.execute(
                "INSERT INTO users (id, display_name, email, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("usr_legacy", "Legacy", "legacy@example.test", "active", "2026-07-30T00:00:00+00:00", "2026-07-30T00:00:00+00:00"),
            )
            connection.execute(
                """
                INSERT INTO research_profiles (
                    id, user_id, version, is_current, base_profile, research_topic,
                    include_keywords_json, exclude_keywords_json, source_ids_json,
                    journal_ids_json, content_preferences_json, max_items,
                    llm_provider, llm_model, output_formats_json, created_at
                ) VALUES (?, ?, 1, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "prof_legacy", "usr_legacy", "chemistry", "Legacy battery report",
                    "[]", "[]", '["arxiv"]', "[]", "[]", 12,
                    "openai", "gpt-5.4-mini", '["docx"]', "2026-07-30T00:00:00+00:00",
                ),
            )
            connection.commit()
        finally:
            connection.close()

        legacy_repository = PersonalizationRepository.for_sqlite(legacy_path)
        try:
            legacy_repository.initialize()
            profile = legacy_repository.get_current_profile("usr_legacy")
        finally:
            legacy_repository.close()

        self.assertEqual(profile.input.source_ids, ("arxiv",))
        self.assertEqual(profile.input.source_layer_ids, ())

    def test_libsql_compatible_migration_adds_source_layers_to_a_legacy_database(self) -> None:
        legacy_path = Path(self.tempdir.name) / "libsql-compatible-legacy.db"
        legacy_schema = (Path(__file__).resolve().parents[1] / "personalization/schema.sql").read_text(
            encoding="utf-8"
        ).replace("    lookback_days INTEGER NOT NULL DEFAULT 3,\n", "").replace(
            "    ccf_conference_tiers_json TEXT NOT NULL DEFAULT '[\"A\", \"B\"]',\n", ""
        ).replace("    source_layer_ids_json TEXT NOT NULL DEFAULT '[]',\n", "").replace(
            "    source_id TEXT NOT NULL DEFAULT '',\n", ""
        ).replace("    source_layer TEXT NOT NULL DEFAULT 'academic_research',\n", "").replace(
            "    credibility INTEGER NOT NULL DEFAULT 0,\n", ""
        ).replace("    matched_count INTEGER NOT NULL DEFAULT 0,\n", "").replace(
            "    deduplicated_count INTEGER NOT NULL DEFAULT 0,\n", ""
        ).replace(
            "    selected_count INTEGER NOT NULL DEFAULT 0,\n    error_summary TEXT NOT NULL DEFAULT '',\n",
            "    error_summary TEXT NOT NULL DEFAULT '',\n",
        )
        connection = sqlite3.connect(legacy_path)
        connection.executescript(legacy_schema)
        connection.close()

        class LibsqlCompatibleConnection:
            def __init__(self, path: Path) -> None:
                self._connection = sqlite3.connect(path)

            def execute(self, statement: str, parameters: tuple[object, ...] = ()) -> sqlite3.Cursor:
                return self._connection.execute(statement, parameters)

            def commit(self) -> None:
                self._connection.commit()

            def rollback(self) -> None:
                self._connection.rollback()

            def close(self) -> None:
                self._connection.close()

        repository = PersonalizationRepository(LibsqlCompatibleConnection(legacy_path))
        try:
            repository.initialize()
            columns = repository._table_columns("research_profiles")
            source_columns = repository._table_columns("source_metrics")
            migration = repository._fetchone(
                "SELECT name FROM schema_migrations WHERE name = ?", ("profile_source_layers_v1",)
            )
            source_migration = repository._fetchone(
                "SELECT name FROM schema_migrations WHERE name = ?", ("source_funnel_metrics_v1",)
            )
        finally:
            repository.close()

        self.assertIn("source_layer_ids_json", columns)
        self.assertEqual(repository._value(migration, "name"), "profile_source_layers_v1")
        self.assertTrue(
            {
                "source_id",
                "source_layer",
                "credibility",
                "matched_count",
                "deduplicated_count",
                "selected_count",
            }.issubset(source_columns)
        )
        self.assertEqual(repository._value(source_migration, "name"), "source_funnel_metrics_v1")

    def test_stale_local_replica_profile_defaults_missing_lookback_column_to_three_days(self) -> None:
        user_id = self.repository.create_user_with_profile(
            self.user(), self.profile("battery"), self.daily_schedule()
        )
        row = dict(
            self.repository._fetchone(
                "SELECT * FROM research_profiles WHERE user_id = ? AND is_current = 1", (user_id,)
            )
        )
        row.pop("lookback_days")
        row.pop("ccf_conference_tiers_json")
        row.pop("source_layer_ids_json")

        profile = self.repository._profile_from_row(row)

        self.assertEqual(profile.input.lookback_days, 3)
        self.assertEqual(profile.input.ccf_conference_tiers, ("A", "B"))
        self.assertEqual(profile.input.source_layer_ids, ())

    def test_duplicate_automatic_claim_for_same_user_local_date_returns_existing_delivery(self) -> None:
        user_id = self.repository.create_user_with_profile(
            self.user(), self.profile("battery"), self.daily_schedule()
        )
        due = self.repository.make_due_schedule(
            user_id=user_id,
            local_date=date(2026, 7, 28),
            due_at=datetime(2026, 7, 27, 23, 30, tzinfo=timezone.utc),
        )

        first = self.repository.enqueue_automatic_delivery(due)
        second = self.repository.enqueue_automatic_delivery(due)

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.delivery_id, second.delivery_id)
        self.assertEqual(len(self.repository.list_deliveries_for_user(user_id)), 1)
        report_runs = self.repository._fetchall("SELECT id FROM report_runs")
        self.assertEqual(len(report_runs), 1)

        self.repository.set_schedule_next_run(due.schedule_id, due.due_at)
        repaired = self.repository.enqueue_automatic_delivery(due)
        self.assertFalse(repaired.created)
        self.assertEqual(self.repository.get_schedule(user_id).next_run_at, due.due_at)

    def test_manual_send_uses_the_users_local_date(self) -> None:
        user_id = self.repository.create_user_with_profile(
            self.user(), self.profile("battery"), self.daily_schedule()
        )

        delivery = self.repository.create_manual_send(
            user_id, datetime(2026, 7, 27, 16, 30, tzinfo=timezone.utc)
        )

        self.assertEqual(delivery.report_date, date(2026, 7, 28))
        row = self.repository._fetchone(
            "SELECT idempotency_key FROM deliveries WHERE id = ?", (delivery.delivery_id,)
        )
        self.assertEqual(
            self.repository._value(row, "idempotency_key"),
            f"manual_send:{user_id}:2026-07-28:email",
        )

    def test_manual_send_has_no_schedule_id(self) -> None:
        user_id = self.repository.create_user_with_profile(
            self.user(), self.profile("battery"), self.daily_schedule()
        )

        delivery = self.repository.create_manual_send(
            user_id, datetime(2026, 7, 27, 16, 30, tzinfo=timezone.utc)
        )

        self.assertEqual(delivery.schedule_id, "")

    def test_manual_send_reuses_the_existing_delivery_for_a_repeated_same_day_click(self) -> None:
        user_id = self.repository.create_user_with_profile(
            self.user(), self.profile("battery"), self.daily_schedule()
        )

        first = self.repository.create_manual_send(
            user_id, datetime(2026, 7, 27, 16, 30, tzinfo=timezone.utc)
        )
        second = self.repository.create_manual_send(
            user_id, datetime(2026, 7, 28, 15, 59, tzinfo=timezone.utc)
        )

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.delivery_id, second.delivery_id)
        self.assertEqual(first.report_run_id, second.report_run_id)
        self.assertEqual(len(self.repository.list_deliveries_for_user(user_id)), 1)
        self.assertEqual(len(self.repository._fetchall("SELECT id FROM report_runs")), 1)

    def test_manual_send_rejects_a_paused_user(self) -> None:
        user_id = self.repository.create_user_with_profile(
            self.user(), self.profile("battery"), self.daily_schedule()
        )
        self.repository.set_user_status(user_id, "paused")

        with self.assertRaisesRegex(ValueError, "active"):
            self.repository.create_manual_send(
                user_id, datetime(2026, 7, 27, 16, 30, tzinfo=timezone.utc)
            )

        self.assertEqual(self.repository.list_deliveries_for_user(user_id), [])

    def test_manual_send_claim_rechecks_that_the_user_is_active(self) -> None:
        user_id = self.repository.create_user_with_profile(
            self.user(), self.profile("battery"), self.daily_schedule()
        )
        delivery = self.repository.create_manual_send(
            user_id, datetime(2026, 7, 27, 16, 30, tzinfo=timezone.utc)
        )
        self.repository.set_user_status(user_id, "paused")

        claim = self.repository.claim_queued_manual_send(
            delivery.delivery_id,
            now_utc=datetime(2026, 7, 27, 16, 31, tzinfo=timezone.utc),
        )
        record = self.repository.get_delivery(delivery.delivery_id)

        self.assertIsNone(claim)
        self.assertEqual(record.status, "queued")
        self.assertEqual(record.attempt_count, 0)

    def test_successful_automatic_delivery_advances_next_run(self) -> None:
        user_id = self.repository.create_user_with_profile(
            self.user(), self.profile("battery"), self.daily_schedule()
        )
        due_at = datetime(2026, 7, 27, 23, 30, tzinfo=timezone.utc)
        due = self.repository.make_due_schedule(user_id, date(2026, 7, 28), due_at)
        self.repository.set_schedule_next_run(due.schedule_id, due_at)
        delivery = self.repository.enqueue_automatic_delivery(due, due_at)
        claim = self.repository.claim_delivery(delivery.delivery_id, "worker-a", due_at)

        self.assertIsNotNone(claim)
        self.repository.mark_sent(delivery.delivery_id, due_at)

        schedule = self.repository.get_schedule(user_id)
        row = self.repository._fetchone("SELECT last_run_at FROM schedules WHERE id = ?", (due.schedule_id,))
        self.assertEqual(schedule.next_run_at, datetime(2026, 7, 28, 23, 30, tzinfo=timezone.utc))
        self.assertEqual(self.repository._value(row, "last_run_at"), due_at.isoformat())

    def test_history_for_user_returns_existing_main_prepare_items_mapping(self) -> None:
        user_id = self.repository.create_user_with_profile(
            self.user(), self.profile("battery"), self.daily_schedule()
        )
        delivery = self.repository.create_manual_preview(user_id, date(2026, 7, 28))
        item = main.NewsItem(
            title="Battery interface transport",
            source="arXiv",
            published=datetime(2026, 7, 28, tzinfo=timezone.utc),
            link="https://example.test/battery",
            doi="10.1000/test",
            field_name="综合化学",
            score=12.5,
            base_score=12.5,
        )
        effective_profile = main.resolve_profile("chemistry")

        self.repository.record_report_items(
            delivery.report_run_id,
            user_id,
            date(2026, 7, 28),
            effective_profile,
            [item],
        )
        history = self.repository.history_for_user(user_id, date(2026, 7, 29), 10)

        self.assertIn("doi:10.1000/test", history["identity_keys"])
        self.assertIn(main.title_fingerprint(item.title), history["title_keys"])
        self.assertIn(main.topic_signature(item, effective_profile), history["topic_keys"])

    def test_delivery_task_metrics_are_scoped_to_the_delivery_report_run(self) -> None:
        first_user = self.repository.create_user_with_profile(
            self.user(), self.profile("battery"), self.daily_schedule()
        )
        second_user = self.repository.create_user_with_profile(
            UserInput.from_form("Bob", "bob@example.test", "active"),
            self.profile("cathode"),
            self.daily_schedule(),
        )
        first = self.repository.create_manual_preview(first_user, date(2026, 7, 28))
        second = self.repository.create_manual_preview(second_user, date(2026, 7, 28))
        first_source = main.source_status("arXiv", True, "arxiv", item_count=7)
        first_source.matched_count = 5
        first_source.deduplicated_count = 4
        first_source.selected_count = 3
        self.repository.record_generation_metrics(
            first.report_run_id,
            collected_count=7,
            matched_count=5,
            deduplicated_count=4,
            history_excluded_count=1,
            selected_count=3,
            ai_generated=True,
            profile_filter_fallback=False,
            source_statuses=[first_source],
        )
        self.repository.record_generation_metrics(
            second.report_run_id,
            collected_count=9,
            matched_count=9,
            deduplicated_count=8,
            history_excluded_count=0,
            selected_count=5,
            ai_generated=True,
            profile_filter_fallback=False,
            source_statuses=[main.SourceStatus("PubMed", False, 0, "timeout")],
        )

        metrics = self.repository.get_delivery_task_metrics(first.delivery_id)

        self.assertEqual(metrics["collected_count"], 7)
        self.assertEqual(metrics["matched_count"], 5)
        self.assertEqual(metrics["deduplicated_count"], 4)
        self.assertEqual(metrics["history_excluded_count"], 1)
        self.assertEqual(metrics["selected_count"], 3)
        self.assertEqual(
            metrics["sources"],
            [
                {
                    "name": "arXiv",
                    "source_id": "arxiv",
                    "source_layer": "academic_research",
                    "credibility": 3,
                    "success": True,
                    "item_count": 7,
                    "matched_count": 5,
                    "deduplicated_count": 4,
                    "selected_count": 3,
                    "error": "",
                }
            ],
        )

    def test_operations_snapshot_and_pause_change_user_state(self) -> None:
        user_id = self.repository.create_user_with_profile(
            self.user(), self.profile("battery"), self.daily_schedule()
        )

        before = self.repository.operations_snapshot()
        self.repository.set_user_status(user_id, "paused")
        users = self.repository.list_users()

        self.assertEqual(before["total_users"], 1)
        self.assertEqual(users[0].status, "paused")
        self.assertFalse(users[0].schedule_enabled)

    def test_delete_user_cascades_owned_records_and_stops_future_delivery(self) -> None:
        user_id, delivery_id = self.create_user_and_mark_preview_ready(schedule_enabled=True)
        delivery = self.repository.get_delivery(delivery_id)
        item = main.NewsItem(
            title="Battery interface transport",
            source="arXiv",
            published=datetime(2026, 7, 28, tzinfo=timezone.utc),
            link="https://example.test/battery",
            doi="10.1000/test",
            field_name="综合化学",
            score=12.5,
            base_score=12.5,
        )
        self.repository.record_report_items(
            delivery.report_run_id,
            user_id,
            date(2026, 7, 28),
            main.resolve_profile("chemistry"),
            [item],
        )
        self.repository.record_source_statuses(
            delivery.report_run_id, [main.SourceStatus("arXiv", True, 1)]
        )

        self.assertTrue(self.repository.delete_user(user_id))
        self.assertEqual(self.repository.list_users(), [])
        self.assertIsNone(
            self.repository._fetchone("SELECT id FROM schedules WHERE user_id = ?", (user_id,))
        )
        for table in (
            "research_profiles",
            "report_runs",
            "deliveries",
            "report_items",
            "run_events",
            "source_metrics",
        ):
            self.assertEqual(
                self.repository._fetchone(f"SELECT COUNT(*) AS count FROM {table}")["count"],
                0,
            )
        self.assertEqual(self.repository.list_due_schedules(datetime.now(timezone.utc)), [])
        self.assertFalse(self.repository.delete_user(user_id))

    def test_schedule_can_be_updated_without_rewriting_delivery_history(self) -> None:
        user_id = self.repository.create_user_with_profile(
            self.user(), self.profile("battery"), self.daily_schedule()
        )
        updated_schedule = ScheduleInput.from_form(
            "weekly", 2, "Asia/Shanghai", "08:15", True
        )

        self.repository.update_schedule(user_id, updated_schedule)
        schedule = self.repository.get_schedule(user_id)

        self.assertEqual(schedule.frequency, "weekly")
        self.assertEqual(schedule.weekday, 2)
        self.assertEqual(schedule.local_send_time, "08:15")

    def test_disabled_schedule_is_not_due_until_approved_preview_enables_it(self) -> None:
        now = datetime(2026, 7, 28, 0, 0, tzinfo=timezone.utc)
        user_id, delivery_id = self.create_user_and_mark_preview_ready(schedule_enabled=False)
        disabled_schedule = self.repository.get_schedule(user_id)
        self.repository.set_schedule_next_run(disabled_schedule.id, now)

        self.assertEqual(self.repository.list_due_schedules(now), [])

        schedule = self.repository.activate_schedule_after_preview(user_id, delivery_id, now)

        self.assertTrue(schedule.enabled)
        self.assertEqual(schedule.next_run_at, datetime(2026, 7, 28, 23, 30, tzinfo=timezone.utc))
        self.assertEqual(self.repository.get_delivery(delivery_id).status, "preview_ready")
        recent_delivery = self.repository.list_recent_deliveries()[0]
        self.assertEqual(recent_delivery["user_id"], user_id)
        self.assertTrue(recent_delivery["schedule_enabled"])
        event = self.repository._fetchone(
            "SELECT event_type FROM run_events WHERE delivery_id = ? AND event_type = 'schedule_activated'",
            (delivery_id,),
        )
        self.assertEqual(self.repository._value(event, "event_type"), "schedule_activated")

    def test_activation_rejects_another_users_preview_or_a_non_ready_preview(self) -> None:
        now = datetime(2026, 7, 28, 0, 0, tzinfo=timezone.utc)
        user_id, delivery_id = self.create_user_and_mark_preview_ready(schedule_enabled=False)
        other_user_id = self.repository.create_user_with_profile(
            UserInput.from_form("Bob", "bob@example.test", "active"),
            self.profile("cathode"),
            self.disabled_daily_schedule(),
        )
        queued_preview = self.repository.create_manual_preview(user_id, date(2026, 7, 29))

        with self.assertRaisesRegex(ValueError, "preview_ready"):
            self.repository.activate_schedule_after_preview(other_user_id, delivery_id, now)
        with self.assertRaisesRegex(ValueError, "preview_ready"):
            self.repository.activate_schedule_after_preview(user_id, queued_preview.delivery_id, now)

        self.assertFalse(self.repository.get_schedule(other_user_id).enabled)
        self.assertFalse(self.repository.get_schedule(user_id).enabled)

    def test_remote_turso_connection_uses_a_portable_transaction_begin(self) -> None:
        calls: list[str] = []

        class FakeConnection:
            def execute(self, statement: str, parameters=()):
                calls.append(statement)

            def commit(self) -> None:
                calls.append("commit")

            def rollback(self) -> None:
                calls.append("rollback")

        connection = FakeConnection()
        module = types.SimpleNamespace(
            connect=lambda database, auth_token: (
                self.assertEqual(database, "libsql://dashboard.example"),
                self.assertEqual(auth_token, "test-token"),
                connection,
            )[-1]
        )

        with (
            mock.patch.dict(
                os.environ,
                {"TURSO_DATABASE_URL": "libsql://dashboard.example", "TURSO_AUTH_TOKEN": "test-token"},
                clear=True,
            ),
            mock.patch.dict(sys.modules, {"libsql": module}),
        ):
            repository = PersonalizationRepository.from_environment()
            with repository._transaction():
                pass

        self.assertEqual(calls, ["BEGIN", "commit"])

    def test_environment_repository_uses_local_sqlite_when_configured(self) -> None:
        database_path = Path(self.tempdir.name) / "scheduler-local.db"

        with mock.patch.dict(
            os.environ,
            {"PERSONAL_ADMIN_LOCAL_DB": str(database_path)},
            clear=True,
        ):
            repository = PersonalizationRepository.from_environment()
            try:
                repository.initialize()
                self.assertIsInstance(repository.connection, sqlite3.Connection)
            finally:
                repository.close()

    def test_local_replica_connection_uses_local_path_and_manual_sync(self) -> None:
        calls: list[tuple[object, ...] | str] = []

        class FakeReplicaConnection:
            def sync(self) -> None:
                calls.append("sync")

        connection = FakeReplicaConnection()
        module = types.SimpleNamespace(
            connect=lambda **kwargs: (
                calls.append(("connect", kwargs)),
                connection,
            )[-1]
        )

        with mock.patch.dict(sys.modules, {"libsql": module}):
            repository = PersonalizationRepository.for_local_replica(
                Path("/tmp/dashboard-replica.db"),
                "libsql://dashboard.example",
                "test-token",
            )
            self.assertTrue(repository.is_local_replica)
            self.assertTrue(repository.sync())

        self.assertEqual(
            calls,
            [
                (
                    "connect",
                    {
                        "database": "/tmp/dashboard-replica.db",
                        "sync_url": "libsql://dashboard.example",
                        "auth_token": "test-token",
                        "_check_same_thread": False,
                    },
                ),
                "sync",
            ],
        )

    def test_replica_becomes_readable_only_after_a_successful_sync_brings_the_schema(self) -> None:
        class FakeCursor:
            def __init__(self, row: tuple[int] | None) -> None:
                self.row = row

            def fetchone(self) -> tuple[int] | None:
                return self.row

        class FakeReplicaConnection:
            def __init__(self) -> None:
                self.synced = False

            def execute(self, statement: str, parameters=()) -> FakeCursor:
                del statement, parameters
                return FakeCursor((1,) if self.synced else None)

            def sync(self) -> None:
                self.synced = True

        connection = FakeReplicaConnection()
        module = types.SimpleNamespace(connect=lambda **kwargs: connection)

        with mock.patch.dict(sys.modules, {"libsql": module}):
            repository = PersonalizationRepository.for_local_replica(
                Path("/tmp/dashboard-replica.db"),
                "libsql://dashboard.example",
                "test-token",
            )
            self.assertFalse(repository.is_local_data_ready)

            repository.sync()

        self.assertTrue(repository.is_local_data_ready)

    def test_manual_sync_bootstraps_the_existing_schema_for_an_empty_primary(self) -> None:
        class FakeCursor:
            def __init__(self, row: tuple[int] | None = None) -> None:
                self.row = row

            def fetchone(self) -> tuple[int] | None:
                return self.row

        class FakeReplicaConnection:
            def __init__(self) -> None:
                self.has_schema = False
                self.statements: list[str] = []
                self.sync_calls = 0

            def execute(self, statement: str, parameters=()) -> FakeCursor:
                del parameters
                if "sqlite_master" in statement:
                    return FakeCursor((1,) if self.has_schema else None)
                self.statements.append(statement)
                if "CREATE TABLE IF NOT EXISTS users" in statement:
                    self.has_schema = True
                return FakeCursor()

            def commit(self) -> None:
                pass

            def sync(self) -> None:
                self.sync_calls += 1

        connection = FakeReplicaConnection()
        module = types.SimpleNamespace(connect=lambda **kwargs: connection)

        with mock.patch.dict(sys.modules, {"libsql": module}):
            repository = PersonalizationRepository.for_local_replica(
                Path("/tmp/dashboard-replica.db"),
                "libsql://dashboard.example",
                "test-token",
            )
            repository.sync()

        self.assertTrue(repository.is_local_data_ready)
        self.assertGreaterEqual(connection.sync_calls, 2)
        self.assertTrue(any("CREATE TABLE IF NOT EXISTS users" in sql for sql in connection.statements))

    def test_plain_sqlite_repository_has_no_remote_sync(self) -> None:
        self.assertFalse(self.repository.is_local_replica)
        self.assertFalse(self.repository.sync())

    def test_sqlite_repository_is_usable_from_a_later_streamlit_rerun_thread(self) -> None:
        errors: list[Exception] = []

        def read_snapshot() -> None:
            try:
                self.repository.operations_snapshot()
            except Exception as exc:  # pragma: no cover - assertion below records the error.
                errors.append(exc)

        rerun_thread = threading.Thread(target=read_snapshot)
        rerun_thread.start()
        rerun_thread.join()

        self.assertEqual(errors, [])

    def test_replica_sync_records_a_non_sensitive_failure_state(self) -> None:
        class FailingReplicaConnection:
            def sync(self) -> None:
                raise ConnectionError("token=must-not-appear")

        repository = PersonalizationRepository(FailingReplicaConnection(), is_local_replica=True)

        with self.assertRaises(ConnectionError):
            repository.sync()

        self.assertIsNone(repository.last_sync_at)
        self.assertEqual(repository.last_sync_error, "ConnectionError")

    def test_manual_retry_command_rejects_an_automatic_delivery(self) -> None:
        user_id = self.repository.create_user_with_profile(
            self.user(), self.profile("battery"), self.daily_schedule()
        )
        due = self.repository.make_due_schedule(
            user_id, date(2026, 7, 28), datetime(2026, 7, 27, 23, 30, tzinfo=timezone.utc)
        )
        delivery = self.repository.enqueue_automatic_delivery(due)
        self.assertIsNotNone(self.repository.claim_delivery(delivery.delivery_id))
        self.repository.mark_retryable_failure(delivery.delivery_id, "synthetic failure")

        self.assertIsNone(self.repository.retry_delivery(delivery.delivery_id))

    def test_cancelling_a_claimed_delivery_keeps_it_terminal_and_skips_the_period(self) -> None:
        user_id = self.repository.create_user_with_profile(
            self.user(), self.profile("battery"), self.daily_schedule()
        )
        due_at = datetime(2026, 7, 27, 23, 30, tzinfo=timezone.utc)
        due = self.repository.make_due_schedule(user_id, date(2026, 7, 28), due_at)
        self.repository.set_schedule_next_run(due.schedule_id, due_at)
        delivery = self.repository.enqueue_automatic_delivery(due, due_at)
        self.assertIsNotNone(self.repository.claim_delivery(delivery.delivery_id, "worker-a", due_at))

        cancelled = self.repository.cancel_delivery(
            delivery.delivery_id, datetime(2026, 7, 28, 0, 0, tzinfo=timezone.utc)
        )

        record = self.repository.get_delivery(delivery.delivery_id)
        report_run = self.repository._fetchone(
            "SELECT status, error_summary FROM report_runs WHERE id = ?", (delivery.report_run_id,)
        )
        self.assertTrue(cancelled)
        self.assertEqual(record.status, "cancelled")
        self.assertEqual(record.execution_id, "")
        self.assertEqual(record.next_retry_at, "")
        self.assertIsNone(self.repository.claim_delivery(delivery.delivery_id, "worker-b"))
        self.assertEqual(self.repository._value(report_run, "status"), "failed")
        self.assertEqual(self.repository._value(report_run, "error_summary"), "Cancelled by operator")
        self.assertEqual(
            self.repository.get_schedule(user_id).next_run_at,
            datetime(2026, 7, 28, 23, 30, tzinfo=timezone.utc),
        )

    def test_cancelling_a_claimed_preview_prevents_it_from_becoming_ready(self) -> None:
        user_id = self.repository.create_user_with_profile(
            self.user(), self.profile("battery"), self.disabled_daily_schedule()
        )
        preview = self.repository.create_manual_preview(user_id, date(2026, 7, 28))
        self.assertIsNotNone(self.repository.claim_delivery(preview.delivery_id))
        self.assertTrue(self.repository.cancel_delivery(preview.delivery_id))

        self.repository.mark_preview_ready(
            preview.delivery_id, preview.report_run_id, "preview-artifact", "preview-run"
        )

        self.assertEqual(self.repository.get_delivery(preview.delivery_id).status, "cancelled")
        report_run = self.repository._fetchone(
            "SELECT status FROM report_runs WHERE id = ?", (preview.report_run_id,)
        )
        self.assertEqual(self.repository._value(report_run, "status"), "failed")

    def test_successful_preview_retry_clears_the_previous_failure_details(self) -> None:
        user_id = self.repository.create_user_with_profile(
            self.user(), self.profile("battery"), self.disabled_daily_schedule()
        )
        preview = self.repository.create_manual_preview(user_id, date(2026, 7, 28))
        self.assertIsNotNone(self.repository.claim_delivery(preview.delivery_id))
        self.repository.mark_retryable_failure(preview.delivery_id, "fetch", "no matching items")
        self.assertEqual(self.repository.retry_delivery(preview.delivery_id), "preview")
        self.assertIsNotNone(self.repository.claim_delivery(preview.delivery_id))

        self.assertTrue(
            self.repository.mark_preview_ready(
                preview.delivery_id, preview.report_run_id, "preview-artifact", "preview-run"
            )
        )

        delivery = self.repository.get_delivery(preview.delivery_id)
        self.assertEqual(delivery.status, "preview_ready")
        self.assertEqual(delivery.last_error, "")
        self.assertEqual(delivery.error_stage, "")
        self.assertEqual(delivery.next_retry_at, "")

    @unittest.skipUnless(importlib.util.find_spec("libsql"), "libsql is not installed")
    def test_real_libsql_tuple_rows_are_read_by_column_name(self) -> None:
        import libsql

        repository = PersonalizationRepository(libsql.connect(":memory:"))
        try:
            repository.initialize()
            user_id = repository.create_user_with_profile(
                self.user(), self.profile("battery"), self.daily_schedule()
            )

            profile = repository.get_current_profile(user_id)
            users = repository.list_users()
        finally:
            repository.close()

        self.assertEqual(profile.input.research_topic, "Lithium metal batteries")
        self.assertEqual(users[0].display_name, "Alice")

    def test_expired_claim_is_recovered_for_a_later_retry(self) -> None:
        user_id = self.repository.create_user_with_profile(
            self.user(), self.profile("battery"), self.daily_schedule()
        )
        delivery = self.repository.create_manual_preview(user_id, date(2026, 7, 28))
        self.assertIsNotNone(self.repository.claim_delivery(delivery.delivery_id))
        now = datetime(2026, 7, 28, 3, 0, tzinfo=timezone.utc)
        self.repository._execute(
            "UPDATE deliveries SET updated_at = ?, locked_at = ? WHERE id = ?",
            (
                (now - timedelta(minutes=121)).isoformat(),
                (now - timedelta(minutes=121)).isoformat(),
                delivery.delivery_id,
            ),
        )
        self.repository.connection.commit()

        recovered = self.repository.recover_expired_deliveries(now, lease_minutes=120)

        self.assertEqual(recovered, [delivery.delivery_id])
        self.assertEqual(self.repository.get_delivery(delivery.delivery_id).status, "retryable_failed")
