"""Tests for the Prometheus result formatting and the not-configured guard.
These run without a live Prometheus by exercising the pure formatting helpers
and by clearing the configured URL."""

from __future__ import annotations

import devops_agent.tools.prometheus as prom
from devops_agent.config import get_settings


def test_parse_duration():
    assert prom._parse_duration("30m", 0) == 1800
    assert prom._parse_duration("1h", 0) == 3600
    assert prom._parse_duration("2d", 0) == 172800
    assert prom._parse_duration("", 99) == 99
    assert prom._parse_duration("garbage", 7) == 7
    assert prom._parse_duration("45", 0) == 45


def test_fmt_labels():
    assert prom._fmt_labels({"__name__": "up", "job": "api", "instance": "x"}) == 'up{instance="x",job="api"}'
    assert prom._fmt_labels({"__name__": "up"}) == "up"


def test_format_vector_result():
    payload = {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [
                {"metric": {"__name__": "up", "job": "payments"}, "value": [1719000000, "1"]},
                {"metric": {"__name__": "up", "job": "redis"}, "value": [1719000000, "0"]},
            ],
        },
    }
    out = prom._format_result(payload)
    assert "2 series" in out
    assert 'up{job="payments"} => 1' in out
    assert 'up{job="redis"} => 0' in out


def test_format_matrix_result():
    payload = {
        "status": "success",
        "data": {
            "resultType": "matrix",
            "result": [
                {
                    "metric": {"__name__": "latency", "svc": "checkout"},
                    "values": [[1, "0.1"], [2, "0.5"], [3, "0.9"]],
                }
            ],
        },
    }
    out = prom._format_result(payload)
    assert "points=3" in out and "last=0.9" in out and "max=0.9" in out


def test_format_error_result():
    payload = {"status": "error", "error": "bad query"}
    assert "Prometheus error" in prom._format_result(payload)


def test_query_not_configured(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "prometheus_url", None)
    out = prom.prometheus_query.invoke({"query": "up"})
    assert "not configured" in out
    assert "DEVOPS_AGENT_PROMETHEUS_URL" in out
