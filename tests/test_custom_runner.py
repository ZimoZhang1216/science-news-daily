import os
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest import mock

import custom_user_daily
import main
from personalization.custom_runner import (
    RunnerServices,
    deliver_manual_send,
    generate_preview,
    run_due_deliveries,
)
from personalization.models import ResearchProfileInput, ScheduleInput, UserInput
from personalization.repository import PersonalizationRepository


class CustomRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.tempdir.name) / "output"
        self.repository = PersonalizationRepository.for_sqlite(Path(self.tempdir.name) / "admin.db")
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
        self.mailer_calls: list[Path] = []
        self.generated_options: list[main.ReportGenerationOptions] = []

    def tearDown(self) -> None:
        self.repository.close()
        self.tempdir.cleanup()

    def successful_generator(
        self,
        options: main.ReportGenerationOptions,
        profile: dict,
        history: dict[str, set[str]],
        item_filter,
        supplement_filter,
    ) -> main.ReportGenerationResult:
        self.generated_options.append(options)
        output_path = options.output_dir / "report.docx"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"docx")
        item = main.NewsItem(
            title="Battery interface transport",
            source="arXiv",
            published=datetime(2026, 7, 28, tzinfo=UTC),
            link="https://example.test/battery",
            abstract="Battery ion transport study.",
            item_id="N001",
            field_name="综合化学",
            score=12.0,
            base_score=12.0,
        )
        self.assertTrue(item_filter(item))
        return main.ReportGenerationResult(
            output_path=output_path,
            selected_items=[item],
            source_statuses=[
                main.SourceStatus(
                    "arXiv",
                    True,
                    1,
                    source_id="arxiv",
                    source_layer="academic_research",
                    credibility=3,
                    matched_count=1,
                    deduplicated_count=1,
                    selected_count=1,
                )
            ],
            report_payload={"ai_generated": True},
            collected_count=1,
            matched_count=1,
            deduplicated_count=1,
            history_excluded_count=0,
            selected_count=1,
            ai_generated=True,
            failure_exit_code=None,
        )

    def failing_generator(
        self,
        options: main.ReportGenerationOptions,
        profile: dict,
        history: dict[str, set[str]],
        item_filter,
        supplement_filter,
    ) -> main.ReportGenerationResult:
        return main.ReportGenerationResult(
            output_path=None,
            selected_items=[],
            source_statuses=[main.SourceStatus("arXiv", False, 0, "timeout")],
            report_payload={},
            collected_count=0,
            matched_count=0,
            deduplicated_count=0,
            history_excluded_count=0,
            selected_count=0,
            ai_generated=False,
            failure_exit_code=4,
        )

    def successful_pdf(self, docx_path: Path) -> Path | None:
        pdf_path = docx_path.with_suffix(".pdf")
        pdf_path.write_bytes(b"%PDF-1.4\n")
        return pdf_path

    def fail_if_called(self, *args, **kwargs):
        raise AssertionError("mailer must not be called for a preview")

    def successful_mailer(self, pdf_path: Path, report_date: date, profile: dict, recipients: list[str]) -> bool:
        self.mailer_calls.append(pdf_path)
        self.assertEqual(recipients, ["alice@example.test"])
        return True

    def retry_with_cli(self, delivery_id: str) -> tuple[int, dict[str, str]]:
        output_path = Path(self.tempdir.name) / "github-output.txt"
        with (
            mock.patch.object(
                custom_user_daily.PersonalizationRepository,
                "from_environment",
                return_value=self.repository,
            ),
            mock.patch.object(
                sys,
                "argv",
                ["custom_user_daily.py", "retry", "--delivery-id", delivery_id],
            ),
            mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(output_path)}, clear=False),
        ):
            exit_code = custom_user_daily.main()
        outputs = dict(
            line.split("=", maxsplit=1)
            for line in output_path.read_text(encoding="utf-8").splitlines()
        )
        return exit_code, outputs

    def test_preview_generates_pdf_without_sending_email(self) -> None:
        claim = self.repository.create_manual_preview(self.user_id, date(2026, 7, 28))
        services = RunnerServices(
            generator=self.successful_generator,
            pdf_converter=self.successful_pdf,
            mailer=self.fail_if_called,
            github_run_id="123",
            output_root=self.output_dir,
        )

        exit_code = generate_preview(self.repository, claim.delivery_id, services)
        delivery = self.repository.get_delivery(claim.delivery_id)

        self.assertEqual(exit_code, 0)
        self.assertEqual(self.mailer_calls, [])
        self.assertEqual(delivery.status, "preview_ready")
        self.assertEqual(delivery.artifact_name, f"custom-report-{delivery.report_run_id}")
        self.assertTrue((self.output_dir / delivery.id / "report.pdf").is_file())
        metrics = self.repository.get_delivery_task_metrics(delivery.id)
        self.assertEqual(metrics["collected_count"], 1)
        self.assertEqual(metrics["matched_count"], 1)
        self.assertEqual(metrics["deduplicated_count"], 1)
        self.assertEqual(metrics["history_excluded_count"], 0)
        self.assertEqual(metrics["selected_count"], 1)
        self.assertEqual(
            metrics["sources"],
            [
                {
                    "name": "arXiv",
                    "source_id": "arxiv",
                    "source_layer": "academic_research",
                    "credibility": 3,
                    "success": True,
                    "item_count": 1,
                    "matched_count": 1,
                    "deduplicated_count": 1,
                    "selected_count": 1,
                    "error": "",
                }
            ],
        )

    def test_preview_becomes_retryable_when_pdf_conversion_fails(self) -> None:
        """A preview is not ready until its downloadable PDF has been created."""

        claim = self.repository.create_manual_preview(self.user_id, date(2026, 7, 28))
        services = RunnerServices(
            generator=self.successful_generator,
            pdf_converter=self.fail_if_called,
            mailer=self.fail_if_called,
            github_run_id="123",
            output_root=self.output_dir,
        )

        exit_code = generate_preview(self.repository, claim.delivery_id, services)
        delivery = self.repository.get_delivery(claim.delivery_id)

        self.assertEqual(exit_code, 4)
        self.assertEqual(delivery.status, "retryable_failed")
        self.assertEqual(delivery.error_stage, "pdf")

    def test_preview_uses_the_saved_profile_lookback_window(self) -> None:
        current = self.repository.get_current_profile(self.user_id).input
        self.repository.save_profile_version(self.user_id, replace(current, lookback_days=60))
        claim = self.repository.create_manual_preview(self.user_id, date(2026, 7, 28))
        services = RunnerServices(
            generator=self.successful_generator,
            pdf_converter=self.successful_pdf,
            mailer=self.fail_if_called,
            github_run_id="123",
            output_root=self.output_dir,
        )

        with mock.patch.dict("os.environ", {"CUSTOM_REPORT_DAYS": "1"}):
            exit_code = generate_preview(self.repository, claim.delivery_id, services)

        self.assertEqual(exit_code, 0)
        self.assertEqual(self.generated_options[-1].days, 60)

    def test_preview_uses_the_saved_candidate_collection_budget(self) -> None:
        current = self.repository.get_current_profile(self.user_id).input
        self.repository.save_profile_version(self.user_id, replace(current, candidate_limit=500))
        claim = self.repository.create_manual_preview(self.user_id, date(2026, 7, 28))
        services = RunnerServices(
            generator=self.successful_generator,
            pdf_converter=self.successful_pdf,
            mailer=self.fail_if_called,
            github_run_id="123",
            output_root=self.output_dir,
        )

        with mock.patch.dict("os.environ", {"CHEM_NEWS_SOURCE_LIMIT": "1"}):
            exit_code = generate_preview(self.repository, claim.delivery_id, services)

        self.assertEqual(exit_code, 0)
        self.assertEqual(self.generated_options[-1].source_limit, 500)

    def test_preview_with_an_unsupported_saved_profile_becomes_retryable(self) -> None:
        """A profile introduced by a newer deployment must not leave a claimed preview stuck."""

        claim = self.repository.create_manual_preview(self.user_id, date(2026, 7, 28))
        self.repository._execute(
            "UPDATE research_profiles SET base_profile = ? WHERE user_id = ? AND version = 1",
            ("future_profile", self.user_id),
        )
        self.repository.connection.commit()
        services = RunnerServices(
            generator=self.successful_generator,
            pdf_converter=self.successful_pdf,
            mailer=self.fail_if_called,
            github_run_id="123",
            output_root=self.output_dir,
        )

        try:
            exit_code = generate_preview(self.repository, claim.delivery_id, services)
        except ValueError:
            exit_code = "uncaught-profile-error"
        delivery = self.repository.get_delivery(claim.delivery_id)

        self.assertEqual(exit_code, 4)
        self.assertEqual(delivery.status, "retryable_failed")
        self.assertEqual(delivery.error_stage, "profile")

    def test_manual_send_emails_one_pdf_without_advancing_the_schedule(self) -> None:
        """A manual send must not consume the user's next scheduled delivery."""

        delivery = self.repository.create_manual_send(
            self.user_id, datetime(2026, 7, 28, 3, 0, tzinfo=UTC)
        )
        next_run_at = self.repository.get_schedule(self.user_id).next_run_at
        services = RunnerServices(
            generator=self.successful_generator,
            pdf_converter=self.successful_pdf,
            mailer=self.successful_mailer,
            github_run_id="123",
            output_root=self.output_dir,
        )

        exit_code = deliver_manual_send(
            self.repository,
            delivery.delivery_id,
            services,
            datetime(2026, 7, 28, 3, 0, tzinfo=UTC),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(self.mailer_calls, [self.output_dir / delivery.delivery_id / "report.pdf"])
        self.assertEqual(self.repository.get_delivery(delivery.delivery_id).status, "sent")
        self.assertEqual(self.repository.get_schedule(self.user_id).next_run_at, next_run_at)

    def test_failed_manual_send_retry_routes_to_deliver_and_eventually_sends(self) -> None:
        delivery = self.repository.create_manual_send(
            self.user_id, datetime(2026, 7, 28, 3, 0, tzinfo=UTC)
        )
        failing_services = RunnerServices(
            generator=self.failing_generator,
            pdf_converter=self.successful_pdf,
            mailer=self.fail_if_called,
            github_run_id="123",
            output_root=self.output_dir,
        )

        first_exit = deliver_manual_send(
            self.repository,
            delivery.delivery_id,
            failing_services,
            datetime(2026, 7, 28, 3, 0, tzinfo=UTC),
        )
        retry_exit, outputs = self.retry_with_cli(delivery.delivery_id)
        successful_services = RunnerServices(
            generator=self.successful_generator,
            pdf_converter=self.successful_pdf,
            mailer=self.successful_mailer,
            github_run_id="124",
            output_root=self.output_dir,
        )
        second_exit = deliver_manual_send(
            self.repository,
            delivery.delivery_id,
            successful_services,
            datetime(2026, 7, 28, 3, 31, tzinfo=UTC),
        )

        self.assertEqual(first_exit, 4)
        self.assertEqual(retry_exit, 0)
        self.assertEqual(
            outputs,
            {"next_command": "deliver", "delivery_id": delivery.delivery_id},
        )
        self.assertEqual(second_exit, 0)
        self.assertEqual(self.repository.get_delivery(delivery.delivery_id).status, "sent")
        self.assertEqual(
            self.mailer_calls,
            [self.output_dir / delivery.delivery_id / "report.pdf"],
        )

    def test_manual_send_generator_exception_becomes_retryable_document_failure(self) -> None:
        delivery = self.repository.create_manual_send(
            self.user_id, datetime(2026, 7, 28, 3, 0, tzinfo=UTC)
        )

        def raising_generator(*args, **kwargs):
            raise RuntimeError("generation failed")

        exit_code = deliver_manual_send(
            self.repository,
            delivery.delivery_id,
            RunnerServices(
                generator=raising_generator,
                pdf_converter=self.successful_pdf,
                mailer=self.fail_if_called,
                github_run_id="123",
                output_root=self.output_dir,
            ),
            datetime(2026, 7, 28, 3, 0, tzinfo=UTC),
        )
        failed = self.repository.get_delivery(delivery.delivery_id)

        self.assertEqual(exit_code, 4)
        self.assertEqual(failed.status, "retryable_failed")
        self.assertEqual(failed.error_stage, "document")
        self.assertEqual(
            self.repository.retry_delivery(delivery.delivery_id), "deliver"
        )

    def test_manual_send_pdf_exception_becomes_retryable_pdf_failure(self) -> None:
        delivery = self.repository.create_manual_send(
            self.user_id, datetime(2026, 7, 28, 3, 0, tzinfo=UTC)
        )

        def raising_pdf_converter(docx_path: Path) -> Path | None:
            raise RuntimeError("pdf failed")

        exit_code = deliver_manual_send(
            self.repository,
            delivery.delivery_id,
            RunnerServices(
                generator=self.successful_generator,
                pdf_converter=raising_pdf_converter,
                mailer=self.fail_if_called,
                github_run_id="123",
                output_root=self.output_dir,
            ),
            datetime(2026, 7, 28, 3, 0, tzinfo=UTC),
        )
        failed = self.repository.get_delivery(delivery.delivery_id)

        self.assertEqual(exit_code, 4)
        self.assertEqual(failed.status, "retryable_failed")
        self.assertEqual(failed.error_stage, "pdf")
        self.assertEqual(
            self.repository.retry_delivery(delivery.delivery_id), "deliver"
        )

    def test_manual_send_mailer_exception_becomes_retryable_email_failure(self) -> None:
        delivery = self.repository.create_manual_send(
            self.user_id, datetime(2026, 7, 28, 3, 0, tzinfo=UTC)
        )

        def raising_mailer(*args, **kwargs) -> bool:
            raise RuntimeError("smtp failed")

        exit_code = deliver_manual_send(
            self.repository,
            delivery.delivery_id,
            RunnerServices(
                generator=self.successful_generator,
                pdf_converter=self.successful_pdf,
                mailer=raising_mailer,
                github_run_id="123",
                output_root=self.output_dir,
            ),
            datetime(2026, 7, 28, 3, 0, tzinfo=UTC),
        )
        failed = self.repository.get_delivery(delivery.delivery_id)

        self.assertEqual(exit_code, 3)
        self.assertEqual(failed.status, "retryable_failed")
        self.assertEqual(failed.error_stage, "email")
        self.assertEqual(
            self.repository.retry_delivery(delivery.delivery_id), "deliver"
        )

    def test_failed_preview_retry_still_routes_to_preview_without_email(self) -> None:
        delivery = self.repository.create_manual_preview(
            self.user_id, date(2026, 7, 28)
        )
        failing_services = RunnerServices(
            generator=self.failing_generator,
            pdf_converter=self.successful_pdf,
            mailer=self.fail_if_called,
            github_run_id="123",
            output_root=self.output_dir,
        )

        first_exit = generate_preview(
            self.repository, delivery.delivery_id, failing_services
        )
        retry_exit, outputs = self.retry_with_cli(delivery.delivery_id)
        successful_services = RunnerServices(
            generator=self.successful_generator,
            pdf_converter=self.successful_pdf,
            mailer=self.fail_if_called,
            github_run_id="124",
            output_root=self.output_dir,
        )
        second_exit = generate_preview(
            self.repository, delivery.delivery_id, successful_services
        )

        self.assertEqual(first_exit, 4)
        self.assertEqual(retry_exit, 0)
        self.assertEqual(
            outputs,
            {"next_command": "preview", "delivery_id": delivery.delivery_id},
        )
        self.assertEqual(second_exit, 0)
        self.assertEqual(
            self.repository.get_delivery(delivery.delivery_id).status,
            "preview_ready",
        )
        self.assertEqual(self.mailer_calls, [])

    def test_manual_send_does_not_claim_scheduled_or_preview_deliveries(self) -> None:
        """The direct send route must never claim another delivery category."""

        scheduled_due = self.repository.make_due_schedule(
            user_id=self.user_id,
            local_date=date(2026, 7, 28),
            due_at=datetime(2026, 7, 27, 23, 30, tzinfo=UTC),
        )
        scheduled = self.repository.enqueue_automatic_delivery(scheduled_due)
        preview = self.repository.create_manual_preview(self.user_id, date(2026, 7, 28))
        services = RunnerServices(
            generator=self.successful_generator,
            pdf_converter=self.successful_pdf,
            mailer=self.successful_mailer,
            github_run_id="123",
            output_root=self.output_dir,
        )
        now = datetime(2026, 7, 28, 3, 0, tzinfo=UTC)

        scheduled_exit = deliver_manual_send(self.repository, scheduled.delivery_id, services, now)
        preview_exit = deliver_manual_send(self.repository, preview.delivery_id, services, now)

        self.assertEqual(scheduled_exit, 0)
        self.assertEqual(preview_exit, 0)
        self.assertEqual(self.mailer_calls, [])
        self.assertEqual(self.repository.get_delivery(scheduled.delivery_id).status, "queued")
        self.assertEqual(self.repository.get_delivery(preview.delivery_id).status, "queued")

    def test_automatic_due_delivery_retries_twice_then_stops(self) -> None:
        due = self.repository.make_due_schedule(
            user_id=self.user_id,
            local_date=date(2026, 7, 28),
            due_at=datetime(2026, 7, 27, 23, 30, tzinfo=UTC),
        )
        self.repository.set_schedule_next_run(due.schedule_id, due.due_at)
        services = RunnerServices(
            generator=self.failing_generator,
            pdf_converter=self.successful_pdf,
            mailer=self.fail_if_called,
            github_run_id="123",
            output_root=self.output_dir,
        )
        now = datetime(2026, 7, 28, 0, 0, tzinfo=UTC)

        run_due_deliveries(self.repository, now, services)
        first_attempt = self.repository.list_deliveries_for_user(self.user_id)[0]
        self.assertEqual(first_attempt.attempt_count, 1)

        run_due_deliveries(self.repository, now + timedelta(minutes=31), services)
        run_due_deliveries(self.repository, now + timedelta(minutes=92), services)

        delivery = self.repository.list_deliveries_for_user(self.user_id)[0]
        self.assertEqual(delivery.status, "failed")
        self.assertEqual(delivery.attempt_count, 3)
        metrics = self.repository.get_delivery_task_metrics(delivery.id)
        self.assertEqual(metrics["collected_count"], 0)
        self.assertEqual(
            metrics["sources"],
            [
                {
                    "name": "arXiv",
                    "source_id": "arxiv",
                    "source_layer": "academic_research",
                    "credibility": 3,
                    "success": False,
                    "item_count": 0,
                    "matched_count": 0,
                    "deduplicated_count": 0,
                    "selected_count": 0,
                    "error": "timeout",
                }
            ],
        )

    def test_expired_automatic_claim_waits_until_the_next_scan_before_retrying(self) -> None:
        due = self.repository.make_due_schedule(
            user_id=self.user_id,
            local_date=date(2026, 7, 28),
            due_at=datetime(2026, 7, 27, 23, 30, tzinfo=UTC),
        )
        delivery = self.repository.enqueue_automatic_delivery(due)
        self.assertIsNotNone(self.repository.claim_delivery(delivery.delivery_id))
        now = datetime(2026, 7, 28, 3, 0, tzinfo=UTC)
        self.repository._execute(
            "UPDATE deliveries SET updated_at = ?, locked_at = ? WHERE id = ?",
            (
                (now - timedelta(minutes=121)).isoformat(),
                (now - timedelta(minutes=121)).isoformat(),
                delivery.delivery_id,
            ),
        )
        self.repository.connection.commit()
        services = RunnerServices(
            generator=self.failing_generator,
            pdf_converter=self.successful_pdf,
            mailer=self.fail_if_called,
            github_run_id="123",
            output_root=self.output_dir,
        )

        self.assertEqual(run_due_deliveries(self.repository, now, services), 0)
        recovered = self.repository.get_delivery(delivery.delivery_id)

        self.assertEqual(recovered.status, "retryable_failed")
        self.assertEqual(recovered.attempt_count, 1)
