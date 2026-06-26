"""Shared HTTP helper for observability backends (Prometheus, Grafana, Datadog).

Centralizes auth, timeouts, error handling, and redaction so each backend's
tools stay thin. Returns parsed JSON for tools that want to format it, or a
ready-to-show error string when the call fails.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from ..config import Settings, get_settings
from ..safety import redact


@dataclass
class HttpResult:
    ok: bool
    status: int
    data: Any | None
    error: str | None = None


def request_json(
    method: str,
    base_url: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: Any | None = None,
    headers: dict[str, str] | None = None,
    token: str | None = None,
    auth: tuple[str, str] | None = None,
    settings: Settings | None = None,
) -> HttpResult:
    """Make an HTTP request and parse a JSON response into an `HttpResult`.

    `token` sets a Bearer header; `auth` sets HTTP basic auth (user, secret) —
    used by backends like Jenkins. Never raises — network/parse failures come
    back as `ok=False` with an error string suitable for handing to the model.
    """
    settings = settings or get_settings()
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    hdrs = {"Accept": "application/json"}
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    if headers:
        hdrs.update(headers)
    try:
        with httpx.Client(timeout=settings.http_timeout) as client:
            resp = client.request(method, url, params=params, json=json_body, headers=hdrs, auth=auth)
    except httpx.HTTPError as exc:
        return HttpResult(ok=False, status=0, data=None, error=f"{type(exc).__name__}: {exc}")

    body: Any
    try:
        body = resp.json()
    except ValueError:
        body = resp.text

    if resp.status_code >= 400:
        snippet = body if isinstance(body, str) else json.dumps(body)[:500]
        return HttpResult(
            ok=False,
            status=resp.status_code,
            data=body,
            error=f"HTTP {resp.status_code}: {redact(str(snippet))[:500]}",
        )
    return HttpResult(ok=True, status=resp.status_code, data=body)


_DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_duration(text: str, default_seconds: int) -> int:
    """Parse "30m" / "1h" / "2d" / "45" into seconds; fall back to a default."""
    text = (text or "").strip()
    if not text:
        return default_seconds
    if text.isdigit():
        return int(text)
    unit, body = text[-1], text[:-1]
    if unit in _DURATION_UNITS and body.lstrip("-").isdigit():
        return int(body) * _DURATION_UNITS[unit]
    return default_seconds


def dump_json(value: Any, max_chars: int | None = None) -> str:
    """Pretty-print a JSON-able value, redacted and truncated for the model."""
    settings = get_settings()
    limit = max_chars or settings.max_output_chars
    text = redact(json.dumps(value, indent=2, default=str))
    if len(text) > limit:
        text = text[: limit - 80] + "\n... [truncated; narrow the query/time range]"
    return text
