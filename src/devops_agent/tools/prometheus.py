"""Prometheus triage tools — query metrics, alerts, and scrape targets.

Talks to the Prometheus HTTP API directly (no exporter/agent in between). Query
results are formatted compactly (one line per series) instead of dumped as raw
JSON, so the model can reason over them without burning the context window.
"""

from __future__ import annotations

import time
from typing import Any

from langchain_core.tools import tool

from ..config import get_settings
from .base import not_configured
from .obs_http import dump_json, request_json

_DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def _parse_duration(text: str, default_seconds: int) -> int:
    text = (text or "").strip()
    if not text:
        return default_seconds
    unit = text[-1]
    if unit in _DURATION_UNITS and text[:-1].lstrip("-").isdigit():
        return int(text[:-1]) * _DURATION_UNITS[unit]
    if text.isdigit():
        return int(text)
    return default_seconds


def _fmt_labels(metric: dict[str, str]) -> str:
    name = metric.get("__name__", "")
    labels = {k: v for k, v in metric.items() if k != "__name__"}
    label_str = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return f"{name}{{{label_str}}}" if label_str else name or "{}"


def _format_result(payload: dict[str, Any], max_series: int = 50) -> str:
    if payload.get("status") != "success":
        return f"Prometheus error: {payload.get('error', payload)}"
    data = payload.get("data", {})
    rtype = data.get("resultType")
    result = data.get("result", [])

    if rtype == "vector" and not result:
        return "Query succeeded but returned no series (empty result)."

    if rtype == "vector":
        lines = []
        for series in result[:max_series]:
            value = series.get("value", [None, "?"])[1]
            lines.append(f"{_fmt_labels(series.get('metric', {}))} => {value}")
        extra = f"\n... (+{len(result) - max_series} more series)" if len(result) > max_series else ""
        return f"{len(result)} series:\n" + "\n".join(lines) + extra

    if rtype == "matrix":
        lines = []
        for series in result[:max_series]:
            values = series.get("values", [])
            nums = [float(v[1]) for v in values if v[1] not in ("NaN", None)]
            last = values[-1][1] if values else "?"
            stats = f"points={len(values)} last={last}"
            if nums:
                stats += f" min={min(nums):.4g} max={max(nums):.4g}"
            lines.append(f"{_fmt_labels(series.get('metric', {}))} => {stats}")
        extra = f"\n... (+{len(result) - max_series} more series)" if len(result) > max_series else ""
        return f"{len(result)} series over time:\n" + "\n".join(lines) + extra

    if rtype in ("scalar", "string"):
        return f"{rtype}: {result}"
    return dump_json(payload)


def _prom_base() -> str | None:
    return get_settings().prometheus_url


def _prom_get(path: str, params: dict[str, Any] | None = None):
    settings = get_settings()
    return request_json(
        "GET", settings.prometheus_url, path, params=params, token=settings.prometheus_token, settings=settings
    )


@tool
def prometheus_query(query: str, at_time: str = "") -> str:
    """Run an instant PromQL query against Prometheus.

    Use to check a metric's current value: error rates, saturation, queue depth,
    replica counts, etc. Example queries:
      sum(rate(http_requests_total{job="payments",code=~"5.."}[5m]))
      kube_pod_container_status_restarts_total{namespace="prod"}

    Args:
        query: A PromQL expression.
        at_time: Optional RFC3339 timestamp or unix seconds to evaluate at; empty = now.
    """
    if not _prom_base():
        return not_configured("Prometheus", "DEVOPS_AGENT_PROMETHEUS_URL")
    params: dict[str, Any] = {"query": query}
    if at_time:
        params["time"] = at_time
    res = _prom_get("/api/v1/query", params)
    if not res.ok:
        return f"Prometheus query failed: {res.error}"
    return _format_result(res.data)


@tool
def prometheus_query_range(query: str, lookback: str = "1h", step: str = "1m") -> str:
    """Run a PromQL range query over a recent time window.

    Use to see a metric's trend (did it spike, when?). Returns per-series point
    counts and min/max/last rather than every datapoint.

    Args:
        query: A PromQL expression.
        lookback: How far back from now, e.g. "30m", "1h", "6h", "1d".
        step: Resolution between points, e.g. "30s", "1m", "5m".
    """
    if not _prom_base():
        return not_configured("Prometheus", "DEVOPS_AGENT_PROMETHEUS_URL")
    end = time.time()
    start = end - _parse_duration(lookback, 3600)
    params = {"query": query, "start": f"{start:.0f}", "end": f"{end:.0f}", "step": step or "1m"}
    res = _prom_get("/api/v1/query_range", params)
    if not res.ok:
        return f"Prometheus range query failed: {res.error}"
    return _format_result(res.data)


@tool
def prometheus_alerts() -> str:
    """List currently firing and pending Prometheus alerts.

    Use early in triage to see what the platform already thinks is wrong, with
    each alert's labels (severity, service, namespace) and active-since time.
    """
    if not _prom_base():
        return not_configured("Prometheus", "DEVOPS_AGENT_PROMETHEUS_URL")
    res = _prom_get("/api/v1/alerts")
    if not res.ok:
        return f"Prometheus alerts query failed: {res.error}"
    alerts = res.data.get("data", {}).get("alerts", [])
    if not alerts:
        return "No active alerts."
    lines = []
    for a in alerts:
        labels = a.get("labels", {})
        name = labels.get("alertname", "?")
        sev = labels.get("severity", "")
        extra = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()) if k not in ("alertname", "severity"))
        lines.append(f"[{a.get('state', '?')}] {name} severity={sev} {{{extra}}} since={a.get('activeAt', '?')}")
    return f"{len(alerts)} active alert(s):\n" + "\n".join(lines)


@tool
def prometheus_targets(only_unhealthy: bool = True) -> str:
    """List Prometheus scrape targets and their health (up/down).

    Use when metrics are missing or stale — a down target means Prometheus isn't
    scraping that service, so its metrics/alerts are blind.

    Args:
        only_unhealthy: If true, show only targets that are not "up".
    """
    if not _prom_base():
        return not_configured("Prometheus", "DEVOPS_AGENT_PROMETHEUS_URL")
    res = _prom_get("/api/v1/targets")
    if not res.ok:
        return f"Prometheus targets query failed: {res.error}"
    active = res.data.get("data", {}).get("activeTargets", [])
    rows = []
    for t in active:
        health = t.get("health", "unknown")
        if only_unhealthy and health == "up":
            continue
        labels = t.get("labels", {})
        job = labels.get("job", "?")
        inst = labels.get("instance", "?")
        err = t.get("lastError", "")
        rows.append(f"[{health}] job={job} instance={inst}" + (f" error={err}" if err else ""))
    if not rows:
        return "All scrape targets are up." if only_unhealthy else "No targets found."
    return f"{len(rows)} target(s):\n" + "\n".join(rows)


@tool
def prometheus_label_values(label: str, match: str = "") -> str:
    """List the values of a label (e.g. discover job, namespace, or pod names).

    Use to find out what to query — e.g. which `job` or `namespace` values exist
    before writing a more specific PromQL expression.

    Args:
        label: Label name, e.g. "job", "namespace", "pod".
        match: Optional series selector to scope it, e.g. 'up{namespace="prod"}'.
    """
    if not _prom_base():
        return not_configured("Prometheus", "DEVOPS_AGENT_PROMETHEUS_URL")
    params = {"match[]": match} if match else None
    res = _prom_get(f"/api/v1/label/{label}/values", params)
    if not res.ok:
        return f"Prometheus label query failed: {res.error}"
    values = res.data.get("data", [])
    return f"{len(values)} value(s) for {label!r}:\n" + ", ".join(map(str, values[:200]))


PROMETHEUS_TOOLS = [
    prometheus_query,
    prometheus_query_range,
    prometheus_alerts,
    prometheus_targets,
    prometheus_label_values,
]
