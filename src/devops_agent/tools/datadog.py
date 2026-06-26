"""Datadog triage tools (read-only Datadog API).

Covers the three things you reach into Datadog for during an incident: a metric's
recent values, matching logs, and which monitors are alerting. Authenticates with
the API + application keys; the API host is derived from the configured site.
"""

from __future__ import annotations

import time

from langchain_core.tools import tool

from ..config import get_settings
from .base import not_configured
from .obs_http import parse_duration, request_json


def _configured() -> bool:
    s = get_settings()
    return bool(s.datadog_api_key and s.datadog_app_key)


def _dd_base() -> str:
    return f"https://api.{get_settings().datadog_site}"


def _dd_headers() -> dict[str, str]:
    s = get_settings()
    return {"DD-API-KEY": s.datadog_api_key or "", "DD-APPLICATION-KEY": s.datadog_app_key or ""}


def _missing() -> str:
    return not_configured("Datadog", "DD_API_KEY", "DD_APP_KEY")


@tool
def datadog_metric_query(query: str, lookback: str = "1h") -> str:
    """Query a Datadog timeseries metric over a recent window.

    Use to check a metric's recent values/trend. Example queries:
      avg:system.cpu.user{service:payments}
      sum:trace.http.request.errors{env:prod} by {service}

    Args:
        query: A Datadog metrics query string.
        lookback: How far back from now, e.g. "30m", "1h", "6h".
    """
    if not _configured():
        return _missing()
    to = int(time.time())
    frm = to - parse_duration(lookback, 3600)
    res = request_json(
        "GET",
        _dd_base(),
        "/api/v1/query",
        params={"from": frm, "to": to, "query": query},
        headers=_dd_headers(),
    )
    if not res.ok:
        return f"Datadog metric query failed: {res.error}"
    series = res.data.get("series", []) if isinstance(res.data, dict) else []
    if not series:
        return f"No data for query {query!r} (status={res.data.get('status') if isinstance(res.data, dict) else '?'})."
    lines = []
    for s in series[:50]:
        points = [p[1] for p in s.get("pointlist", []) if p and p[1] is not None]
        last = points[-1] if points else "?"
        stats = f"last={last}"
        if points:
            stats += f" min={min(points):.4g} max={max(points):.4g}"
        lines.append(f"{s.get('scope', s.get('metric', '?'))} => {stats}")
    return f"{len(series)} series:\n" + "\n".join(lines)


@tool
def datadog_logs_search(query: str = "*", lookback: str = "15m", limit: int = 25) -> str:
    """Search Datadog logs.

    Use to pull the actual log lines behind an alert or error spike. Example
    queries: 'service:payments status:error', '@http.status_code:500 env:prod'.

    Args:
        query: A Datadog log search query.
        lookback: How far back from now, e.g. "15m", "1h".
        limit: Max log events to return.
    """
    if not _configured():
        return _missing()
    body = {
        "filter": {"query": query, "from": f"now-{lookback}", "to": "now"},
        "sort": "-timestamp",
        "page": {"limit": min(limit, 100)},
    }
    res = request_json(
        "POST",
        _dd_base(),
        "/api/v2/logs/events/search",
        json_body=body,
        headers={**_dd_headers(), "Content-Type": "application/json"},
    )
    if not res.ok:
        return f"Datadog logs search failed: {res.error}"
    events = res.data.get("data", []) if isinstance(res.data, dict) else []
    if not events:
        return f"No logs matched {query!r} in the last {lookback}."
    lines = []
    for e in events:
        attr = e.get("attributes", {})
        ts = attr.get("timestamp", "?")
        svc = attr.get("service", "-")
        status = attr.get("status", "-")
        msg = (attr.get("message", "") or "").replace("\n", " ")[:200]
        lines.append(f"{ts} [{status}] {svc}: {msg}")
    return f"{len(events)} log line(s):\n" + "\n".join(lines)


@tool
def datadog_monitors(only_alerting: bool = True) -> str:
    """List Datadog monitors and their state.

    Use to see what Datadog already considers broken. By default shows only
    monitors that are not OK (Alert / Warn / No Data).

    Args:
        only_alerting: If true, hide monitors in the OK state.
    """
    if not _configured():
        return _missing()
    res = request_json("GET", _dd_base(), "/api/v1/monitor", headers=_dd_headers())
    if not res.ok:
        return f"Datadog monitors query failed: {res.error}"
    monitors = res.data if isinstance(res.data, list) else []
    rows = []
    for m in monitors:
        state = m.get("overall_state", "Unknown")
        if only_alerting and state == "OK":
            continue
        rows.append(f"[{state}] {m.get('name', '?')} (id={m.get('id', '?')})")
    if not rows:
        return "All monitors are OK." if only_alerting else "No monitors found."
    return f"{len(rows)} monitor(s):\n" + "\n".join(rows[:100])


@tool
def datadog_events(lookback: str = "1h", limit: int = 30) -> str:
    """List recent Datadog events (deploys, alerts, changes) in a time window.

    Use to correlate an incident with a recent deploy or config change recorded
    in the Datadog event stream.

    Args:
        lookback: How far back from now, e.g. "1h", "6h".
        limit: Max events to return.
    """
    if not _configured():
        return _missing()
    end = int(time.time())
    start = end - parse_duration(lookback, 3600)
    res = request_json(
        "GET", _dd_base(), "/api/v1/events", params={"start": start, "end": end}, headers=_dd_headers()
    )
    if not res.ok:
        return f"Datadog events query failed: {res.error}"
    events = res.data.get("events", []) if isinstance(res.data, dict) else []
    if not events:
        return f"No events in the last {lookback}."
    lines = []
    for e in events[:limit]:
        atype = e.get("alert_type", "info")
        title = (e.get("title", "") or "").replace("\n", " ")[:120]
        lines.append(f"{e.get('date_happened', '?')} [{atype}] {title}")
    return f"{len(events)} event(s) (showing {min(len(events), limit)}):\n" + "\n".join(lines)


DATADOG_TOOLS = [
    datadog_metric_query,
    datadog_logs_search,
    datadog_monitors,
    datadog_events,
]
