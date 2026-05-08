from __future__ import annotations

import logging
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import requests


DEFAULT_ENDPOINTS = [
    ("arxiv.org", "https://arxiv.org/"),
    ("pubmed.ncbi.nlm.nih.gov", "https://pubmed.ncbi.nlm.nih.gov/"),
    ("api.crossref.org", "https://api.crossref.org/works?rows=0"),
]


@dataclass
class EndpointCheck:
    host: str
    url: str
    dns_ok: bool = False
    dns_error: str = ""
    addresses: list[str] = field(default_factory=list)
    https_ok: bool = False
    http_status: int | None = None
    https_error: str = ""
    dns_elapsed_ms: int = 0
    https_elapsed_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.dns_ok and self.https_ok

    def dns_summary(self) -> str:
        if self.dns_ok:
            return f"成功 ({', '.join(self.addresses[:3])})"
        return f"失败 ({self.dns_error})"

    def https_summary(self) -> str:
        if self.https_ok:
            return f"成功 (HTTP {self.http_status})"
        return f"失败 ({self.https_error})"


@dataclass
class NetworkDiagnostics:
    checked_at: datetime
    endpoints: list[EndpointCheck]

    @property
    def dns_failed_hosts(self) -> list[str]:
        return [endpoint.host for endpoint in self.endpoints if not endpoint.dns_ok]

    @property
    def https_failed_hosts(self) -> list[str]:
        return [endpoint.host for endpoint in self.endpoints if not endpoint.https_ok]

    @property
    def network_ok(self) -> bool:
        return all(endpoint.ok for endpoint in self.endpoints)

    def summary_lines(self) -> list[str]:
        lines = []
        for endpoint in self.endpoints:
            lines.append(
                f"{endpoint.host}: DNS {endpoint.dns_summary()}；HTTPS {endpoint.https_summary()}"
            )
        return lines

    def as_dict(self) -> dict[str, Any]:
        return {
            "checked_at": self.checked_at.isoformat(),
            "network_ok": self.network_ok,
            "dns_failed_hosts": self.dns_failed_hosts,
            "https_failed_hosts": self.https_failed_hosts,
            "endpoints": [
                {
                    "host": endpoint.host,
                    "url": endpoint.url,
                    "dns_ok": endpoint.dns_ok,
                    "dns_error": endpoint.dns_error,
                    "addresses": endpoint.addresses,
                    "https_ok": endpoint.https_ok,
                    "http_status": endpoint.http_status,
                    "https_error": endpoint.https_error,
                }
                for endpoint in self.endpoints
            ],
        }


def _check_dns(host: str, timeout: float) -> tuple[bool, list[str], str, int]:
    previous_timeout = socket.getdefaulttimeout()
    started = time.monotonic()
    try:
        socket.setdefaulttimeout(timeout)
        records = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        addresses = sorted({record[4][0] for record in records})
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return True, addresses, "", elapsed_ms
    except OSError as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return False, [], f"{type(exc).__name__}: {exc}", elapsed_ms
    finally:
        socket.setdefaulttimeout(previous_timeout)


def _check_https(session: requests.Session, url: str, timeout: float) -> tuple[bool, int | None, str, int]:
    started = time.monotonic()
    try:
        response = session.get(url, timeout=timeout)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        status = response.status_code
        if status < 500:
            return True, status, "", elapsed_ms
        return False, status, f"HTTP {status}", elapsed_ms
    except requests.RequestException as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return False, None, f"{type(exc).__name__}: {exc}", elapsed_ms


def run_network_checks(
    endpoints: list[tuple[str, str]] | None = None,
    timeout: float = 8.0,
    logger: logging.Logger | None = None,
) -> NetworkDiagnostics:
    session = requests.Session()
    session.headers.update({"User-Agent": "ScienceNewsDaily/1.0 network-check"})
    checks: list[EndpointCheck] = []

    for host, url in endpoints or DEFAULT_ENDPOINTS:
        dns_ok, addresses, dns_error, dns_elapsed_ms = _check_dns(host, timeout)
        https_ok = False
        http_status: int | None = None
        https_error = "DNS 失败，跳过 HTTPS 请求"
        https_elapsed_ms = 0
        if dns_ok:
            https_ok, http_status, https_error, https_elapsed_ms = _check_https(
                session, url, timeout
            )
        check = EndpointCheck(
            host=host,
            url=url,
            dns_ok=dns_ok,
            dns_error=dns_error,
            addresses=addresses,
            https_ok=https_ok,
            http_status=http_status,
            https_error=https_error,
            dns_elapsed_ms=dns_elapsed_ms,
            https_elapsed_ms=https_elapsed_ms,
        )
        checks.append(check)

    diagnostics = NetworkDiagnostics(checked_at=datetime.now(timezone.utc), endpoints=checks)
    if logger:
        for line in diagnostics.summary_lines():
            if diagnostics.network_ok:
                logger.info("Network check: %s", line)
            else:
                logger.warning("Network check: %s", line)
    return diagnostics


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = run_network_checks(logger=logging.getLogger("network_check"))
    raise SystemExit(0 if result.network_ok else 1)
