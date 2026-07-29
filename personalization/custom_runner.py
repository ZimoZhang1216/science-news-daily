"""Workflow-side execution for personalised preview and automatic deliveries."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import main

from personalization.profile import compose_effective_profile, item_matches_research_profile
from personalization.repository import (
    DeliveryClaim,
    DeliveryExecutionContext,
    PersonalizationRepository,
)


@dataclass(frozen=True)
class RunnerServices:
    generator: Callable[
        [
            main.ReportGenerationOptions,
            dict[str, Any],
            dict[str, set[str]],
            Callable[[main.NewsItem], bool],
        ],
        main.ReportGenerationResult,
    ]
    pdf_converter: Callable[[Path], Path | None]
    mailer: Callable[[Path, date, dict[str, Any], list[str]], bool]
    github_run_id: str
    output_root: Path


@dataclass(frozen=True)
class SchedulerSummary:
    discovered: int = 0
    claimed: int = 0
    sent: int = 0
    skipped: int = 0
    failed: int = 0
    waiting_retry: int = 0
    recovered: int = 0
    has_more_due: bool = False

    @property
    def exit_code(self) -> int:
        return 1 if self.failed else 0

    def __eq__(self, other: object) -> bool:
        if isinstance(other, int):
            return self.exit_code == other
        if isinstance(other, SchedulerSummary):
            return self.as_dict() == other.as_dict()
        return False

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "discovered": self.discovered,
            "claimed": self.claimed,
            "sent": self.sent,
            "skipped": self.skipped,
            "failed": self.failed,
            "waiting_retry": self.waiting_retry,
            "recovered": self.recovered,
            "has_more_due": self.has_more_due,
        }


def default_services(output_root: Path) -> RunnerServices:
    def mailer(pdf_path: Path, report_date: date, profile: dict[str, Any], recipients: list[str]) -> bool:
        return main.send_report_email(
            pdf_path,
            report_date,
            profile,
            ai_generated=True,
            recipient_override=recipients,
            raise_on_transport_error=True,
        )

    return RunnerServices(
        generator=main.generate_report,
        pdf_converter=main.convert_docx_to_pdf,
        mailer=mailer,
        github_run_id=os.getenv("GITHUB_RUN_ID", ""),
        output_root=output_root,
    )


def _positive_env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _generation_options(context: DeliveryExecutionContext, output_root: Path) -> main.ReportGenerationOptions:
    profile = context.profile.input
    return main.ReportGenerationOptions(
        days=_positive_env_int("CUSTOM_REPORT_DAYS", 3),
        max_items=profile.max_items,
        min_items=1,
        source_limit=_positive_env_int("CHEM_NEWS_SOURCE_LIMIT", 80),
        max_ai_items=profile.max_items,
        llm_provider=profile.llm_provider,
        model=profile.llm_model,
        report_date=context.claim.report_date,
        output_dir=output_root / context.claim.delivery_id,
        require_ai=True,
        no_openai=False,
    )


def _generate_claimed_report(
    repository: PersonalizationRepository,
    claim: DeliveryClaim,
    services: RunnerServices,
    now_utc: datetime | None = None,
    *,
    require_pdf: bool = True,
) -> tuple[DeliveryExecutionContext, dict[str, Any], main.ReportGenerationResult, Path | None] | None:
    if repository.is_delivery_cancelled(claim.delivery_id):
        return None
    try:
        context = repository.get_delivery_execution_context(claim.delivery_id)
    except ValueError as exc:
        repository.mark_retryable_failure(claim.delivery_id, "profile", str(exc), now_utc)
        return None
    effective_profile = compose_effective_profile(context.profile.input, claim.user_id)
    options = _generation_options(context, services.output_root)
    result = services.generator(
        options,
        effective_profile,
        repository.history_for_user(claim.user_id, claim.report_date, 10),
        lambda item: item_matches_research_profile(item, context.profile.input),
    )
    if repository.is_delivery_cancelled(claim.delivery_id):
        return None
    if result.failure_exit_code is not None or not result.ai_generated or result.output_path is None:
        stage = result.failure_stage or ("fetch" if result.failure_exit_code is not None else "ai")
        repository.mark_retryable_failure(
            claim.delivery_id, stage, f"{stage.title()} stage did not produce a deliverable report", now_utc
        )
        return None
    pdf_path: Path | None = None
    if require_pdf:
        try:
            pdf_path = services.pdf_converter(result.output_path)
        except Exception as exc:  # noqa: BLE001 - PDF conversion is a separately retryable stage.
            repository.mark_retryable_failure(claim.delivery_id, "pdf", type(exc).__name__, now_utc)
            return None
        if pdf_path is None:
            repository.mark_retryable_failure(claim.delivery_id, "pdf", "PDF conversion failed", now_utc)
            return None
        if repository.is_delivery_cancelled(claim.delivery_id):
            return None
    repository.record_report_items(
        claim.report_run_id,
        claim.user_id,
        claim.report_date,
        effective_profile,
        result.selected_items,
    )
    repository.record_source_statuses(claim.report_run_id, result.source_statuses)
    return context, effective_profile, result, pdf_path


def generate_preview(
    repository: PersonalizationRepository, delivery_id: str, services: RunnerServices
) -> int:
    claim = repository.claim_delivery(delivery_id)
    if claim is None:
        return 0
    if claim.mode != "manual":
        repository.mark_retryable_failure(delivery_id, "Preview command requires a manual delivery")
        return 2
    # A manual preview is a content-review artifact.  Requiring LibreOffice here
    # delays review without improving the later PDF mail-delivery guarantee.
    generated = _generate_claimed_report(repository, claim, services, require_pdf=False)
    if generated is None:
        return 0 if repository.is_delivery_cancelled(delivery_id) else 4
    saved = repository.mark_preview_ready(
        delivery_id,
        claim.report_run_id,
        f"custom-report-{claim.report_run_id}",
        services.github_run_id,
    )
    return 0 if saved or repository.is_delivery_cancelled(delivery_id) else 4


def _send_automatic_claim(
    repository: PersonalizationRepository,
    claim: DeliveryClaim,
    services: RunnerServices,
    now_utc: datetime,
) -> int:
    generated = _generate_claimed_report(repository, claim, services, now_utc)
    if generated is None:
        return 2 if repository.is_delivery_cancelled(claim.delivery_id) else 4
    context, effective_profile, _, pdf_path = generated
    assert pdf_path is not None
    repository.mark_email_prepared(claim.delivery_id, now_utc)
    if not repository.mark_email_sending(claim.delivery_id, now_utc):
        return 2 if repository.is_delivery_cancelled(claim.delivery_id) else 4
    try:
        accepted = services.mailer(pdf_path, claim.report_date, effective_profile, [context.email])
    except Exception as exc:  # noqa: BLE001 - mail transport must not stop the batch.
        try:
            repository.mark_email_outcome_unknown(claim.delivery_id, type(exc).__name__, now_utc)
        except Exception:  # noqa: BLE001 - preserve the existing `sending` marker if the DB is unavailable.
            pass
        return 3
    if not accepted:
        repository.mark_retryable_failure(claim.delivery_id, "email", "SMTP delivery failed", now_utc)
        return 3
    try:
        repository.mark_sent(claim.delivery_id, now_utc)
    except Exception:  # noqa: BLE001 - `sending` is intentionally left for conservative recovery.
        return 3
    return 0


def run_due_deliveries(
    repository: PersonalizationRepository,
    now_utc: datetime,
    services: RunnerServices,
    *,
    max_jobs: int | None = None,
    deadline: datetime | None = None,
    execution_id: str = "scheduler",
) -> SchedulerSummary:
    """Run a bounded batch without allowing one user failure to stop later claims."""

    now_utc = now_utc.astimezone(UTC)
    max_jobs = max_jobs or _positive_env_int("MAX_JOBS_PER_RUN", 10)
    deadline = deadline or (
        datetime.now(UTC) + timedelta(minutes=_positive_env_int("MAX_RUNTIME_MINUTES", 80))
    )
    recovered = repository.recover_expired_deliveries(
        now_utc, _positive_env_int("CUSTOM_DELIVERY_LEASE_MINUTES", 120)
    )
    discovered = len(repository.list_due_schedules(now_utc))
    claimed = sent = failed = skipped = 0

    while claimed < max_jobs and datetime.now(UTC) < deadline:
        claim = repository.claim_next_due_delivery(now_utc, execution_id)
        if claim is None:
            break
        claimed += 1
        try:
            result = _send_automatic_claim(repository, claim, services, now_utc)
        except Exception as exc:  # noqa: BLE001 - record then keep the batch moving.
            if repository.is_delivery_cancelled(claim.delivery_id):
                result = 2
            else:
                repository.mark_retryable_failure(claim.delivery_id, "database", type(exc).__name__, now_utc)
                result = 1
        if result == 0:
            sent += 1
        elif result == 2:
            skipped += 1
        else:
            failed += 1

    has_more_due = bool(repository.list_due_schedules(now_utc)) or bool(
        repository.list_recoverable_automatic_delivery_ids(now_utc)
    )
    waiting_retry = repository.count_waiting_automatic_retries()
    return SchedulerSummary(
        discovered=discovered,
        claimed=claimed,
        sent=sent,
        skipped=skipped,
        failed=failed,
        waiting_retry=waiting_retry,
        recovered=len(recovered),
        has_more_due=has_more_due,
    )
