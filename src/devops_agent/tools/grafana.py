"""Grafana triage tools (read-only Grafana HTTP API).

Useful when Grafana is your window into the platform: find the relevant
dashboard, see which datasources exist, and check Grafana-managed alerts/rules
without leaving the agent.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from ..config import get_settings
from .base import not_configured
from .obs_http import dump_json, request_json


def _grafana_base() -> str | None:
    return get_settings().grafana_url


def _grafana_get(path: str, params: dict[str, Any] | None = None):
    settings = get_settings()
    return request_json(
        "GET", settings.grafana_url, path, params=params, token=settings.grafana_token, settings=settings
    )


@tool
def grafana_health() -> str:
    """Check Grafana's own health (database, version).

    Use to confirm Grafana itself is reachable and healthy before trusting (or
    blaming) what its dashboards/alerts show.
    """
    if not _grafana_base():
        return not_configured("Grafana", "DEVOPS_AGENT_GRAFANA_URL")
    res = _grafana_get("/api/health")
    if not res.ok:
        return f"Grafana health check failed: {res.error}"
    return dump_json(res.data)


@tool
def grafana_search_dashboards(query: str = "", limit: int = 20) -> str:
    """Search Grafana dashboards by title/tag.

    Use to find the dashboard for a service ("payments", "kafka") so you know
    which metrics the team watches and where to look next.

    Args:
        query: Search text; empty lists recent dashboards.
        limit: Max results.
    """
    if not _grafana_base():
        return not_configured("Grafana", "DEVOPS_AGENT_GRAFANA_URL")
    params = {"type": "dash-db", "limit": limit}
    if query:
        params["query"] = query
    res = _grafana_get("/api/search", params)
    if not res.ok:
        return f"Grafana search failed: {res.error}"
    items = res.data if isinstance(res.data, list) else []
    if not items:
        return "No dashboards matched."
    lines = [
        f"- {d.get('title', '?')} (uid={d.get('uid', '?')}) folder={d.get('folderTitle', '-')} url={d.get('url', '')}"
        for d in items
    ]
    return f"{len(items)} dashboard(s):\n" + "\n".join(lines)


@tool
def grafana_list_datasources() -> str:
    """List configured Grafana datasources (name, type, uid).

    Use to discover which Prometheus/Loki/Datadog/CloudWatch datasources are
    wired up — tells you where the metrics and logs actually live.
    """
    if not _grafana_base():
        return not_configured("Grafana", "DEVOPS_AGENT_GRAFANA_URL")
    res = _grafana_get("/api/datasources")
    if not res.ok:
        return f"Grafana datasources query failed: {res.error}"
    items = res.data if isinstance(res.data, list) else []
    if not items:
        return "No datasources configured."
    lines = [f"- {d.get('name', '?')} type={d.get('type', '?')} uid={d.get('uid', '?')}" for d in items]
    return f"{len(items)} datasource(s):\n" + "\n".join(lines)


@tool
def grafana_alerts() -> str:
    """List Grafana-managed alerts that are firing or pending.

    Use to see what Grafana's unified alerting already flagged, with each alert's
    labels and state. Complements prometheus_alerts when alerting lives in Grafana.
    """
    if not _grafana_base():
        return not_configured("Grafana", "DEVOPS_AGENT_GRAFANA_URL")
    res = _grafana_get("/api/prometheus/grafana/api/v1/alerts")
    if not res.ok:
        return f"Grafana alerts query failed: {res.error}"
    alerts = res.data.get("data", {}).get("alerts", []) if isinstance(res.data, dict) else []
    active = [a for a in alerts if a.get("state") in ("firing", "pending", "alerting")]
    if not active:
        return "No firing/pending Grafana alerts."
    lines = []
    for a in active:
        labels = a.get("labels", {})
        name = labels.get("alertname", "?")
        extra = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()) if k != "alertname")
        lines.append(f"[{a.get('state', '?')}] {name} {{{extra}}} since={a.get('activeAt', '?')}")
    return f"{len(active)} alert(s):\n" + "\n".join(lines)


GRAFANA_TOOLS = [
    grafana_health,
    grafana_search_dashboards,
    grafana_list_datasources,
    grafana_alerts,
]
