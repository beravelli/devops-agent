"""Correlation helpers — fast, cross-source situational snapshots.

These compose the single-purpose tools into the "first 30 seconds of triage":
one call that gathers what's firing and what changed across Kubernetes,
Prometheus/Grafana, and Datadog, so the agent can line an incident up against a
recent deploy or alert before drilling down. Backends that aren't configured are
skipped automatically.
"""

from __future__ import annotations

from langchain_core.tools import tool

from .base import cli_tool_output
from .datadog import datadog_events, datadog_monitors
from .grafana import grafana_alerts
from .kubernetes import _kubectl, k8s_get_events
from .prometheus import prometheus_alerts


def _section(title: str, text: str) -> str:
    return f"===== {title} =====\n{(text or '').strip()}"


def _include(result: str) -> bool:
    return "is not configured" not in result


@tool
def incident_snapshot(namespace: str = "", lookback: str = "1h") -> str:
    """One-shot cross-source snapshot of what's firing and what changed recently.

    Use this FIRST for a broad or unknown incident: it gathers recent Kubernetes
    events, firing Prometheus and Grafana alerts, non-OK Datadog monitors, and
    recent Datadog events (deploys/changes) so you can correlate the incident with
    a recent change before drilling into a specific layer. Configured backends
    only — the rest are skipped.

    Args:
        namespace: Kubernetes namespace to scope events to; empty = all namespaces.
        lookback: Window for Datadog events, e.g. "30m", "1h", "6h".
    """
    parts = [
        _section(
            "Kubernetes events",
            k8s_get_events.invoke({"namespace": namespace, "all_namespaces": not namespace}),
        )
    ]
    for title, result in [
        ("Prometheus alerts", prometheus_alerts.invoke({})),
        ("Grafana alerts", grafana_alerts.invoke({})),
        ("Datadog monitors (non-OK)", datadog_monitors.invoke({"only_alerting": True})),
        ("Datadog events", datadog_events.invoke({"lookback": lookback})),
    ]:
        if _include(result):
            parts.append(_section(title, result))
    return "\n\n".join(parts)


@tool
def cluster_health_overview() -> str:
    """Quick cluster-wide health sweep: nodes, not-Running pods, and warnings.

    Use to answer "is the platform itself healthy" — shows node status, every pod
    that isn't Running/Succeeded across all namespaces, and recent Warning events.
    Good when the blast radius is unclear or spans multiple services.
    """
    nodes = cli_tool_output(_kubectl(["get", "nodes", "-o", "wide"]))
    bad_pods = cli_tool_output(
        _kubectl(
            ["get", "pods", "--field-selector=status.phase!=Running,status.phase!=Succeeded", "-o", "wide"],
            all_namespaces=True,
        )
    )
    warnings = cli_tool_output(
        _kubectl(
            ["get", "events", "--field-selector=type=Warning", "--sort-by=.lastTimestamp"],
            all_namespaces=True,
        )
    )
    return "\n\n".join(
        [
            _section("Nodes", nodes),
            _section("Pods not Running/Succeeded (all namespaces)", bad_pods),
            _section("Recent Warning events (all namespaces)", warnings),
        ]
    )


CORRELATION_TOOLS = [
    incident_snapshot,
    cluster_health_overview,
]
