"""Narrow GitHub repository-dispatch client for the local dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import requests


DispatchCommand = Literal["preview", "deliver", "retry"]


@dataclass(frozen=True)
class DispatchSettings:
    repository: str
    token: str


@dataclass(frozen=True)
class DispatchRequest:
    url: str
    headers: dict[str, str]
    json: dict[str, object]


def build_dispatch_request(
    settings: DispatchSettings, command: DispatchCommand, delivery_id: str
) -> DispatchRequest:
    repository = settings.repository.strip().strip("/")
    token = settings.token.strip()
    if repository.count("/") != 1:
        raise ValueError("repository must use owner/repository format")
    if not token:
        raise ValueError("GitHub dispatch token is required")
    if not delivery_id.strip():
        raise ValueError("delivery_id is required")
    if command not in {"preview", "deliver", "retry"}:
        raise ValueError("command must be preview, deliver, or retry")
    return DispatchRequest(
        url=f"https://api.github.com/repos/{repository}/dispatches",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={
            "event_type": "personal-news-command",
            "client_payload": {"command": command, "delivery_id": delivery_id.strip()},
        },
    )


def dispatch_command(
    settings: DispatchSettings, command: DispatchCommand, delivery_id: str
) -> None:
    request = build_dispatch_request(settings, command, delivery_id)
    response = requests.post(
        request.url, headers=request.headers, json=request.json, timeout=20
    )
    response.raise_for_status()
