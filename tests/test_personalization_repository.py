import importlib.util
import os
import sys
import tempfile
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

    def profile(self, keyword: str) -> ResearchProfileInput:
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
            self.user(), self.profile("battery"), self.daily_schedule()
        )

        version_two = self.repository.save_profile_version(user_id, self.profile("solid electrolyte"))
        current = self.repository.get_current_profile(user_id)
        versions = self.repository.list_profile_versions(user_id)

        self.assertEqual(version_two, 2)
        self.assertEqual(current.version, 2)
        self.assertEqual(versions[0].include_keywords, ("battery",))
        self.assertEqual(versions[1].include_keywords, ("solid electrolyte",))

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
        self.assertGreater(self.repository.get_schedule(user_id).next_run_at, due.due_at)

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
            "UPDATE deliveries SET updated_at = ? WHERE id = ?",
            ((now - timedelta(minutes=121)).isoformat(), delivery.delivery_id),
        )
        self.repository.connection.commit()

        recovered = self.repository.recover_expired_deliveries(now, lease_minutes=120)

        self.assertEqual(recovered, [delivery.delivery_id])
        self.assertEqual(self.repository.get_delivery(delivery.delivery_id).status, "retryable_failed")
