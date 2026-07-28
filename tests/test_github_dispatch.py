import unittest
from pathlib import Path

import custom_user_daily
from personalization.github import DispatchSettings, build_dispatch_request


class GitHubDispatchTests(unittest.TestCase):
    def test_cronjob_workflow_is_the_only_automatic_user_scheduler(self) -> None:
        root = Path(__file__).resolve().parents[1]
        cronjob = (root / ".github/workflows/cronjob-daily.yml").read_text(encoding="utf-8")
        custom = (root / ".github/workflows/custom-user-daily.yml").read_text(encoding="utf-8")

        self.assertIn("science-news-daily", cronjob)
        self.assertIn("python custom_user_daily.py scan", cronjob)
        self.assertIn("TURSO_DATABASE_URL", cronjob)
        self.assertIn("database credentials not configured", cronjob)
        self.assertIn("MAX_JOBS_PER_RUN", cronjob)
        self.assertNotIn("\n  schedule:", custom)
        self.assertNotIn("  workflow_dispatch:", custom)
        self.assertNotIn("automatic-scan:", custom)

    def test_user_scheduler_is_not_guarded_by_fixed_report_marker(self) -> None:
        workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/cronjob-daily.yml").read_text(
            encoding="utf-8"
        )

        scheduler_section = workflow.split("user-scheduler:", maxsplit=1)[1]
        self.assertNotIn("steps.cronjob_marker.outputs.cache-hit", scheduler_section)
        self.assertIn("scheduler_summary", scheduler_section)

    def test_command_parser_rejects_unknown_dispatch_command(self) -> None:
        with self.assertRaises(SystemExit):
            custom_user_daily.build_parser().parse_args(["not-a-command"])

    def test_dispatch_request_has_only_the_expected_command_and_delivery_id(self) -> None:
        request = build_dispatch_request(
            DispatchSettings("owner/repo", "token"), "preview", "dlv_123"
        )

        self.assertEqual(request.url, "https://api.github.com/repos/owner/repo/dispatches")
        self.assertEqual(
            request.json,
            {
                "event_type": "personal-news-command",
                "client_payload": {"command": "preview", "delivery_id": "dlv_123"},
            },
        )
        self.assertEqual(request.headers["Accept"], "application/vnd.github+json")
        self.assertEqual(request.headers["Authorization"], "Bearer token")

    def test_dashboard_dispatch_contract_rejects_deliver(self) -> None:
        with self.assertRaises(ValueError):
            build_dispatch_request(
                DispatchSettings("owner/repo", "token"), "deliver", "dlv_123"  # type: ignore[arg-type]
            )
