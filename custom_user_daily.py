#!/usr/bin/env python3
"""GitHub Actions entry point for personalised research-daily tasks."""

from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from personalization.custom_runner import (
    deliver_manual_send,
    default_services,
    generate_preview,
    run_due_deliveries,
)
from personalization.normalization import normalize_existing_profiles
from personalization.repository import PersonalizationRepository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a personalised research-daily workflow task.")
    parser.add_argument(
        "command",
        choices=(
            "scan",
            "preview",
            "deliver",
            "artifact-metadata",
            "normalize-profiles",
            "retry",
        ),
    )
    parser.add_argument("--delivery-id", default="")
    return parser


def _require_delivery_id(parser: argparse.ArgumentParser, delivery_id: str) -> str:
    clean_id = delivery_id.strip()
    if not clean_id:
        parser.error("--delivery-id is required for this command")
    return clean_id


def _emit_output(name: str, value: str) -> None:
    output_path = os.getenv("GITHUB_OUTPUT", "").strip()
    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")
    print(f"{name}={value}")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    repository = PersonalizationRepository.from_environment()
    repository.initialize()
    output_root = Path(os.getenv("CUSTOM_REPORT_OUTPUT_DIR", "./output/custom"))
    services = default_services(output_root)

    if args.command == "scan":
        summary = run_due_deliveries(
            repository,
            datetime.now(UTC),
            services,
            execution_id=os.getenv("GITHUB_RUN_ID", "").strip() or f"scheduler-{uuid.uuid4().hex}",
        )
        print(f"scheduler_summary={json.dumps(summary.as_dict(), sort_keys=True)}")
        return summary.exit_code
    if args.command == "preview":
        return generate_preview(repository, _require_delivery_id(parser, args.delivery_id), services)
    if args.command == "deliver":
        return deliver_manual_send(
            repository,
            _require_delivery_id(parser, args.delivery_id),
            services,
            datetime.now(UTC),
        )
    if args.command == "artifact-metadata":
        delivery_id = _require_delivery_id(parser, args.delivery_id)
        delivery = repository.get_delivery(delivery_id)
        if delivery.status != "preview_ready":
            parser.error("delivery must be in preview_ready state")
        _emit_output("delivery_id", delivery_id)
        _emit_output("artifact_name", delivery.artifact_name)
        _emit_output("artifact_run_id", delivery.artifact_run_id)
        return 0
    if args.command == "normalize-profiles":
        summary = normalize_existing_profiles(repository)
        print(f"profile_normalization_summary={json.dumps(summary.as_dict(), sort_keys=True)}")
        return 1 if summary.failed else 0
    if args.command == "retry":
        delivery_id = _require_delivery_id(parser, args.delivery_id)
        if repository.retry_delivery(delivery_id) is None:
            parser.error("delivery is not retryable")
        _emit_output("next_command", "preview")
        _emit_output("delivery_id", delivery_id)
        return 0

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
