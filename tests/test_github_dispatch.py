import unittest

import custom_user_daily
from personalization.github import DispatchSettings, build_dispatch_request


class GitHubDispatchTests(unittest.TestCase):
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
