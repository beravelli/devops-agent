"""Tests for the correlation snapshot tools. The composed tools are stubbed so no
backend is contacted."""

from __future__ import annotations

import devops_agent.tools.correlation as corr


class _FakeTool:
    def __init__(self, result):
        self._result = result

    def invoke(self, _args):
        return self._result


def test_incident_snapshot_includes_and_skips(monkeypatch):
    monkeypatch.setattr(corr, "k8s_get_events", _FakeTool("Warning  BackOff  pod/x"))
    monkeypatch.setattr(corr, "prometheus_alerts", _FakeTool("[firing] HighErrorRate"))
    # Grafana + Datadog "not configured" → must be skipped
    monkeypatch.setattr(corr, "grafana_alerts", _FakeTool("Grafana is not configured. Set ..."))
    monkeypatch.setattr(corr, "datadog_monitors", _FakeTool("Datadog is not configured. Set ..."))
    monkeypatch.setattr(corr, "datadog_events", _FakeTool("Datadog is not configured. Set ..."))

    out = corr.incident_snapshot.invoke({"namespace": "prod"})
    assert "Kubernetes events" in out and "BackOff" in out
    assert "Prometheus alerts" in out and "HighErrorRate" in out
    assert "Grafana" not in out  # skipped (not configured)
    assert "Datadog" not in out  # skipped (not configured)


def test_incident_snapshot_all_configured(monkeypatch):
    monkeypatch.setattr(corr, "k8s_get_events", _FakeTool("events"))
    monkeypatch.setattr(corr, "prometheus_alerts", _FakeTool("prom"))
    monkeypatch.setattr(corr, "grafana_alerts", _FakeTool("graf"))
    monkeypatch.setattr(corr, "datadog_monitors", _FakeTool("ddmon"))
    monkeypatch.setattr(corr, "datadog_events", _FakeTool("ddev"))
    out = corr.incident_snapshot.invoke({})
    for title in ["Kubernetes events", "Prometheus alerts", "Grafana alerts", "Datadog monitors", "Datadog events"]:
        assert title in out


def test_cluster_health_overview_sections(monkeypatch):
    calls = []

    def fake_cli(cmd, *a, **k):
        calls.append(cmd)
        return "output"

    monkeypatch.setattr(corr, "cli_tool_output", fake_cli)
    out = corr.cluster_health_overview.invoke({})
    assert "Nodes" in out and "Pods not Running" in out and "Recent Warning events" in out
    # One of the kubectl calls uses the not-Running field selector
    joined = [" ".join(c) for c in calls]
    assert any("status.phase!=Running" in j for j in joined)
    assert any("type=Warning" in j for j in joined)
