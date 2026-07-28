import tempfile
import threading
import unittest
import importlib.util
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import main
from personalization.custom_runner import RunnerServices, run_due_deliveries
from personalization.models import ResearchProfileInput, ScheduleInput, UserInput
from personalization.repository import PersonalizationRepository, compute_next_run


class UnifiedSchedulerRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "scheduler.db"
        self.repository = PersonalizationRepository.for_sqlite(self.db_path)
        self.repository.initialize()
        self.user_id = self.repository.create_user_with_profile(
            UserInput.from_form("Alice", "alice@example.test", "active"),
            ResearchProfileInput.from_form(
                base_profile="chemistry",
                research_topic="Lithium metal batteries",
                include_keywords="battery",
                exclude_keywords="",
                source_ids=("arxiv",),
                journal_ids=(),
                content_preferences=("mechanism",),
                max_items=10,
                llm_provider="openai",
                llm_model="gpt-5.4-mini",
                output_formats=("docx", "pdf"),
            ),
            ScheduleInput.from_form("daily", None, "Asia/Shanghai", "07:30", True),
        )
        self.now = datetime(2026, 7, 28, 0, 0, tzinfo=UTC)
        self.schedule = self.repository.get_schedule(self.user_id)
        self.repository.set_schedule_next_run(self.schedule.id, self.now - timedelta(minutes=1))

    def tearDown(self) -> None:
        self.repository.close()
        self.tempdir.cleanup()

    def test_paused_user_is_not_claimed(self) -> None:
        self.repository.set_user_status(self.user_id, "paused")

        claim = self.repository.claim_next_due_delivery(self.now, "worker-a")

        self.assertIsNone(claim)

    def test_resume_calculates_a_future_next_run(self) -> None:
        self.repository.set_user_status(self.user_id, "paused", self.now - timedelta(minutes=1))

        self.repository.set_user_status(self.user_id, "active", self.now)

        self.assertEqual(
            self.repository.get_schedule(self.user_id).next_run_at,
            datetime(2026, 7, 28, 23, 30, tzinfo=UTC),
        )

    def test_queued_delivery_cannot_be_claimed_after_user_is_paused(self) -> None:
        due = self.repository.list_due_schedules(self.now)[0]
        delivery = self.repository.enqueue_automatic_delivery(due, self.now)
        self.repository.set_user_status(self.user_id, "paused")

        claim = self.repository.claim_delivery(delivery.delivery_id, "worker-a", self.now)

        self.assertIsNone(claim)

    def test_initialize_backfills_schedule_id_for_existing_automatic_delivery(self) -> None:
        due = self.repository.list_due_schedules(self.now)[0]
        delivery = self.repository.enqueue_automatic_delivery(due, self.now)
        self.repository._execute(
            "UPDATE deliveries SET schedule_id = '', schedule_period_key = '' WHERE id = ?",
            (delivery.delivery_id,),
        )
        self.repository.connection.commit()

        self.repository.initialize()

        migrated = self.repository.get_delivery(delivery.delivery_id)
        self.assertEqual(migrated.schedule_id, self.schedule.id)
        self.assertEqual(migrated.schedule_period_key, f"legacy:{delivery.delivery_id}")

    def test_two_workers_claim_one_due_period_once(self) -> None:
        first = PersonalizationRepository.for_sqlite(self.db_path)
        second = PersonalizationRepository.for_sqlite(self.db_path)
        first.initialize()
        second.initialize()
        barrier = threading.Barrier(2)
        claims = []

        def claim(repository: PersonalizationRepository, execution_id: str) -> None:
            barrier.wait()
            claims.append(repository.claim_next_due_delivery(self.now, execution_id))

        threads = [
            threading.Thread(target=claim, args=(first, "worker-a")),
            threading.Thread(target=claim, args=(second, "worker-b")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        first.close()
        second.close()

        self.assertEqual(sum(result is not None for result in claims), 1)
        delivery = self.repository.list_deliveries_for_user(self.user_id)[0]
        self.assertEqual(delivery.schedule_id, self.schedule.id)
        self.assertEqual(delivery.schedule_period_key, (self.now - timedelta(minutes=1)).isoformat())
        self.assertIn(delivery.execution_id, {"worker-a", "worker-b"})

    def test_retry_waits_for_backoff_before_claiming_again(self) -> None:
        claim = self.repository.claim_next_due_delivery(self.now, "worker-a")
        assert claim is not None
        self.repository.mark_retryable_failure(claim.delivery_id, "pdf", "conversion failed", self.now)

        self.assertIsNone(self.repository.claim_next_due_delivery(self.now, "worker-b"))
        retry = self.repository.claim_next_due_delivery(self.now + timedelta(minutes=31), "worker-b")

        self.assertIsNotNone(retry)

    def test_expired_sending_delivery_is_not_automatically_retried(self) -> None:
        claim = self.repository.claim_next_due_delivery(self.now, "worker-a")
        assert claim is not None
        self.repository.mark_email_prepared(claim.delivery_id, self.now)
        self.repository.mark_email_sending(claim.delivery_id, self.now)

        recovered = self.repository.recover_expired_deliveries(
            self.now + timedelta(hours=3), lease_minutes=120
        )
        delivery = self.repository.get_delivery(claim.delivery_id)

        self.assertEqual(recovered, [claim.delivery_id])
        self.assertEqual(delivery.status, "failed")
        self.assertEqual(delivery.error_stage, "email_outcome_unknown")

    @unittest.skipUnless(importlib.util.find_spec("libsql"), "libsql is not installed")
    def test_libsql_db_api_claims_due_delivery(self) -> None:
        import libsql

        repository = PersonalizationRepository(libsql.connect(":memory:"))
        try:
            repository.initialize()
            user_id = repository.create_user_with_profile(
                UserInput.from_form("Turso", "turso@example.test", "active"),
                ResearchProfileInput.from_form(
                    base_profile="chemistry",
                    research_topic="Lithium metal batteries",
                    include_keywords="battery",
                    exclude_keywords="",
                    source_ids=("arxiv",),
                    journal_ids=(),
                    content_preferences=("mechanism",),
                    max_items=10,
                    llm_provider="openai",
                    llm_model="gpt-5.4-mini",
                    output_formats=("docx", "pdf"),
                ),
                ScheduleInput.from_form("daily", None, "Asia/Shanghai", "07:30", True),
            )
            schedule = repository.get_schedule(user_id)
            repository.set_schedule_next_run(schedule.id, self.now - timedelta(minutes=1))

            claim = repository.claim_next_due_delivery(self.now, "libsql-worker")

            self.assertIsNotNone(claim)
            assert claim is not None
            self.assertEqual(claim.execution_id, "libsql-worker")
        finally:
            repository.close()


class UnifiedSchedulerTimeTests(unittest.TestCase):
    def test_dst_ambiguous_time_uses_first_occurrence(self) -> None:
        schedule = ScheduleInput.from_form("daily", None, "America/New_York", "01:30", True)

        next_run = compute_next_run(schedule, datetime(2026, 11, 1, 4, 0, tzinfo=UTC))

        self.assertEqual(next_run, datetime(2026, 11, 1, 5, 30, tzinfo=UTC))

    def test_dst_nonexistent_time_resolves_forward(self) -> None:
        schedule = ScheduleInput.from_form("daily", None, "America/New_York", "02:30", True)

        next_run = compute_next_run(schedule, datetime(2026, 3, 8, 5, 0, tzinfo=UTC))

        self.assertEqual(next_run, datetime(2026, 3, 8, 7, 30, tzinfo=UTC))


class UnifiedSchedulerRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repository = PersonalizationRepository.for_sqlite(Path(self.tempdir.name) / "runner.db")
        self.repository.initialize()
        self.output_root = Path(self.tempdir.name) / "output"
        self.now = datetime(2026, 7, 28, 0, 0, tzinfo=UTC)

    def tearDown(self) -> None:
        self.repository.close()
        self.tempdir.cleanup()

    def _user(self, name: str) -> str:
        user_id = self.repository.create_user_with_profile(
            UserInput.from_form(name, f"{name.lower()}@example.test", "active"),
            ResearchProfileInput.from_form(
                base_profile="chemistry",
                research_topic="Lithium metal batteries",
                include_keywords="battery",
                exclude_keywords="",
                source_ids=("arxiv",),
                journal_ids=(),
                content_preferences=("mechanism",),
                max_items=10,
                llm_provider="openai",
                llm_model="gpt-5.4-mini",
                output_formats=("docx", "pdf"),
            ),
            ScheduleInput.from_form("daily", None, "Asia/Shanghai", "07:30", True),
        )
        schedule = self.repository.get_schedule(user_id)
        self.repository.set_schedule_next_run(schedule.id, self.now - timedelta(minutes=1))
        return user_id

    def _generator(self, options, profile, history, item_filter):
        output_path = options.output_dir / "report.docx"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"docx")
        item = main.NewsItem(
            title="Battery interface transport",
            source="arXiv",
            published=self.now,
            link="https://example.test/battery",
            abstract="Battery ion transport study.",
            item_id="N001",
            field_name="综合化学",
            score=12.0,
            base_score=12.0,
        )
        assert item_filter(item)
        return main.ReportGenerationResult(
            output_path=output_path,
            selected_items=[item],
            source_statuses=[main.SourceStatus("arXiv", True, 1)],
            report_payload={"ai_generated": True},
            collected_count=1,
            selected_count=1,
            ai_generated=True,
            failure_exit_code=None,
        )

    def _services(self) -> RunnerServices:
        def pdf_converter(path: Path) -> Path:
            pdf = path.with_suffix(".pdf")
            pdf.write_bytes(b"pdf")
            return pdf

        return RunnerServices(
            generator=self._generator,
            pdf_converter=pdf_converter,
            mailer=lambda *_args: True,
            github_run_id="test-run",
            output_root=self.output_root,
        )

    def test_batch_limit_leaves_remaining_due_user_for_next_scan(self) -> None:
        first = self._user("Alice")
        second = self._user("Bob")

        summary = run_due_deliveries(
            self.repository,
            self.now,
            self._services(),
            max_jobs=1,
            deadline=datetime.now(UTC) + timedelta(minutes=10),
            execution_id="worker-a",
        )

        self.assertEqual(summary.claimed, 1)
        self.assertEqual(summary.sent, 1)
        self.assertTrue(summary.has_more_due)
        self.assertEqual(len(self.repository.list_deliveries_for_user(first)) + len(self.repository.list_deliveries_for_user(second)), 1)

    def test_repeated_scan_does_not_send_the_same_due_period_twice(self) -> None:
        user_id = self._user("Alice")
        calls: list[str] = []
        services = self._services()
        services = RunnerServices(
            generator=services.generator,
            pdf_converter=services.pdf_converter,
            mailer=lambda *_args: calls.append("sent") or True,
            github_run_id=services.github_run_id,
            output_root=services.output_root,
        )

        first = run_due_deliveries(
            self.repository,
            self.now,
            services,
            max_jobs=1,
            deadline=datetime.now(UTC) + timedelta(minutes=10),
            execution_id="worker-a",
        )
        second = run_due_deliveries(
            self.repository,
            self.now,
            services,
            max_jobs=1,
            deadline=datetime.now(UTC) + timedelta(minutes=10),
            execution_id="worker-b",
        )

        self.assertEqual(first.sent, 1)
        self.assertEqual(second.claimed, 0)
        self.assertEqual(calls, ["sent"])
        self.assertEqual(len(self.repository.list_deliveries_for_user(user_id)), 1)

    def test_failed_user_does_not_stop_later_user_delivery(self) -> None:
        failing_user = self._user("Alice")
        successful_user = self._user("Bob")

        def generator(options, profile, history, item_filter):
            if profile["custom_user_id"] == failing_user:
                return main.ReportGenerationResult(
                    output_path=None,
                    selected_items=[],
                    source_statuses=[main.SourceStatus("arXiv", False, 0, "network")],
                    report_payload={},
                    collected_count=0,
                    selected_count=0,
                    ai_generated=False,
                    failure_exit_code=4,
                )
            return self._generator(options, profile, history, item_filter)

        services = self._services()
        services = RunnerServices(
            generator=generator,
            pdf_converter=services.pdf_converter,
            mailer=services.mailer,
            github_run_id=services.github_run_id,
            output_root=services.output_root,
        )
        summary = run_due_deliveries(
            self.repository,
            self.now,
            services,
            max_jobs=2,
            deadline=datetime.now(UTC) + timedelta(minutes=10),
            execution_id="worker-a",
        )

        self.assertEqual(summary.failed, 1)
        self.assertEqual(summary.sent, 1)
        self.assertEqual(summary.waiting_retry, 1)
        self.assertEqual(self.repository.list_deliveries_for_user(failing_user)[0].error_stage, "fetch")
        self.assertEqual(self.repository.list_deliveries_for_user(successful_user)[0].status, "sent")

    def test_word_generation_failure_is_recorded_as_word_stage(self) -> None:
        user_id = self._user("Alice")

        def generator(options, profile, history, item_filter):
            return main.ReportGenerationResult(
                output_path=None,
                selected_items=[],
                source_statuses=[],
                report_payload={"ai_generated": True},
                collected_count=1,
                selected_count=1,
                ai_generated=True,
                failure_exit_code=5,
                failure_stage="word",
            )

        services = self._services()
        summary = run_due_deliveries(
            self.repository,
            self.now,
            RunnerServices(
                generator=generator,
                pdf_converter=services.pdf_converter,
                mailer=services.mailer,
                github_run_id=services.github_run_id,
                output_root=services.output_root,
            ),
            max_jobs=1,
            deadline=datetime.now(UTC) + timedelta(minutes=10),
            execution_id="worker-a",
        )

        self.assertEqual(summary.failed, 1)
        self.assertEqual(self.repository.list_deliveries_for_user(user_id)[0].error_stage, "word")

    def test_smtp_transport_exception_is_not_automatically_retried(self) -> None:
        user_id = self._user("Alice")
        calls: list[str] = []
        services = self._services()

        def uncertain_mailer(*_args) -> bool:
            calls.append("attempted")
            raise ConnectionError("connection closed after DATA")

        services = RunnerServices(
            generator=services.generator,
            pdf_converter=services.pdf_converter,
            mailer=uncertain_mailer,
            github_run_id=services.github_run_id,
            output_root=services.output_root,
        )
        first = run_due_deliveries(
            self.repository,
            self.now,
            services,
            max_jobs=1,
            deadline=datetime.now(UTC) + timedelta(minutes=10),
            execution_id="worker-a",
        )
        second = run_due_deliveries(
            self.repository,
            self.now + timedelta(days=1),
            services,
            max_jobs=1,
            deadline=datetime.now(UTC) + timedelta(minutes=10),
            execution_id="worker-b",
        )

        delivery = self.repository.list_deliveries_for_user(user_id)[0]
        self.assertEqual(first.failed, 1)
        self.assertEqual(second.claimed, 0)
        self.assertEqual(calls, ["attempted"])
        self.assertEqual(delivery.status, "failed")
        self.assertEqual(delivery.error_stage, "email_outcome_unknown")

    def test_explicit_smtp_rejection_enters_backoff_retry(self) -> None:
        user_id = self._user("Alice")
        calls: list[str] = []
        services = self._services()
        services = RunnerServices(
            generator=services.generator,
            pdf_converter=services.pdf_converter,
            mailer=lambda *_args: calls.append("attempted") or False,
            github_run_id=services.github_run_id,
            output_root=services.output_root,
        )

        run_due_deliveries(
            self.repository,
            self.now,
            services,
            max_jobs=1,
            deadline=datetime.now(UTC) + timedelta(minutes=10),
            execution_id="worker-a",
        )
        run_due_deliveries(
            self.repository,
            self.now + timedelta(minutes=31),
            services,
            max_jobs=1,
            deadline=datetime.now(UTC) + timedelta(minutes=10),
            execution_id="worker-b",
        )

        delivery = self.repository.list_deliveries_for_user(user_id)[0]
        self.assertEqual(calls, ["attempted", "attempted"])
        self.assertEqual(delivery.status, "retryable_failed")
        self.assertEqual(delivery.error_stage, "email")
        self.assertEqual(delivery.attempt_count, 2)
