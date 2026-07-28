"""Workflow-side execution for personalised preview and automatic deliveries."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, date, datetime
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


def default_services(output_root: Path) -> RunnerServices:
    def mailer(pdf_path: Path, report_date: date, profile: dict[str, Any], recipients: list[str]) -> bool:
        return main.send_report_email(
            pdf_path,
            report_date,
            profile,
            ai_generated=True,
            recipient_override=recipients,
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
) -> tuple[DeliveryExecutionContext, dict[str, Any], main.ReportGenerationResult, Path | None] | None:
    context = repository.get_delivery_execution_context(claim.delivery_id)
    effective_profile = compose_effective_profile(context.profile.input, claim.user_id)
    options = _generation_options(context, services.output_root)
    result = services.generator(
        options,
        effective_profile,
        repository.history_for_user(claim.user_id, claim.report_date, 10),
        lambda item: item_matches_research_profile(item, context.profile.input),
    )
    if result.failure_exit_code is not None or not result.ai_generated or result.output_path is None:
        repository.mark_retryable_failure(
            claim.delivery_id, "AI summary incomplete or no reportable items"
        )
        return None
    pdf_path = services.pdf_converter(result.output_path)
    if pdf_path is None:
        repository.mark_retryable_failure(claim.delivery_id, "PDF conversion failed")
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
    generated = _generate_claimed_report(repository, claim, services)
    if generated is None:
        return 4
    repository.mark_preview_ready(
        delivery_id,
        claim.report_run_id,
        f"custom-report-{claim.report_run_id}",
        services.github_run_id,
    )
    return 0


def _send_automatic_claim(
    repository: PersonalizationRepository, claim: DeliveryClaim, services: RunnerServices
) -> int:
    generated = _generate_claimed_report(repository, claim, services)
    if generated is None:
        return 4
    context, effective_profile, _, pdf_path = generated
    assert pdf_path is not None
    if not services.mailer(pdf_path, claim.report_date, effective_profile, [context.email]):
        repository.mark_retryable_failure(claim.delivery_id, "SMTP delivery failed")
        return 3
    repository.mark_sent(claim.delivery_id)
    return 0


def run_due_deliveries(
    repository: PersonalizationRepository, now_utc: datetime, services: RunnerServices
) -> int:
    """Run newly due automatic schedules plus unfinished recoverable automatic work."""

    overall = 0
    attempted_delivery_ids = set(
        repository.recover_expired_deliveries(
            now_utc, _positive_env_int("CUSTOM_DELIVERY_LEASE_MINUTES", 120)
        )
    )
    for due in repository.list_due_schedules(now_utc):
        claim = repository.enqueue_automatic_delivery(due)
        if claim.status == "queued":
            current = repository.claim_delivery(claim.delivery_id)
            if current is not None:
                attempted_delivery_ids.add(current.delivery_id)
                overall = max(overall, _send_automatic_claim(repository, current, services))

    for delivery_id in repository.list_recoverable_automatic_delivery_ids():
        if delivery_id in attempted_delivery_ids:
            continue
        retry_claim = repository.claim_automatic_retry(delivery_id)
        if retry_claim is not None:
            overall = max(overall, _send_automatic_claim(repository, retry_claim, services))
    return overall
