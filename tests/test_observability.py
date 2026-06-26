"""Tests for the shared HTTP helper and the Grafana/Datadog tools. The HTTP
layer is stubbed so these run without live backends."""

from __future__ import annotations

import devops_agent.tools.datadog as dd
import devops_agent.tools.grafana as gf
from devops_agent.config import get_settings
from devops_agent.tools.obs_http import HttpResult, parse_duration


def test_parse_duration_shared():
    assert parse_duration("15m", 0) == 900
    assert parse_duration("2h", 0) == 7200
    assert parse_duration("1d", 0) == 86400
    assert parse_duration("", 42) == 42
    assert parse_duration("nope", 5) == 5


def test_grafana_not_configured(monkeypatch):
    monkeypatch.setattr(get_settings(), "grafana_url", None)
    assert "not configured" in gf.grafana_health.invoke({})


def test_grafana_search_formats(monkeypatch):
    monkeypatch.setattr(get_settings(), "grafana_url", "https://grafana.example.com")
    monkeypatch.setattr(
        gf,
        "request_json",
        lambda *a, **k: HttpResult(
            ok=True,
            status=200,
            data=[{"title": "Payments", "uid": "abc", "folderTitle": "Prod", "url": "/d/abc"}],
        ),
    )
    out = gf.grafana_search_dashboards.invoke({"query": "pay"})
    assert "Payments" in out and "uid=abc" in out


def test_datadog_not_configured(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "datadog_api_key", None)
    monkeypatch.setattr(s, "datadog_app_key", None)
    assert "not configured" in dd.datadog_monitors.invoke({})


def test_datadog_metric_formats(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "datadog_api_key", "k")
    monkeypatch.setattr(s, "datadog_app_key", "a")
    monkeypatch.setattr(
        dd,
        "request_json",
        lambda *a, **k: HttpResult(
            ok=True,
            status=200,
            data={"status": "ok", "series": [{"scope": "service:payments", "pointlist": [[1, 1.0], [2, 3.0]]}]},
        ),
    )
    out = dd.datadog_metric_query.invoke({"query": "avg:x{*}"})
    assert "service:payments" in out and "last=3.0" in out and "max=3" in out


def test_datadog_monitors_filters_ok(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "datadog_api_key", "k")
    monkeypatch.setattr(s, "datadog_app_key", "a")
    monkeypatch.setattr(
        dd,
        "request_json",
        lambda *a, **k: HttpResult(
            ok=True,
            status=200,
            data=[
                {"name": "cpu", "overall_state": "OK", "id": 1},
                {"name": "errors", "overall_state": "Alert", "id": 2},
            ],
        ),
    )
    out = dd.datadog_monitors.invoke({"only_alerting": True})
    assert "errors" in out and "Alert" in out
    assert "cpu" not in out
