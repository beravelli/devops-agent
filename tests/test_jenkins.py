"""Tests for the Jenkins CI/CD tools (HTTP layer stubbed)."""

from __future__ import annotations

import devops_agent.tools.jenkins as jk
from devops_agent.config import get_settings
from devops_agent.tools.obs_http import HttpResult


def _enable(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "jenkins_url", "https://jenkins.example.com")
    monkeypatch.setattr(s, "jenkins_user", "ci")
    monkeypatch.setattr(s, "jenkins_token", "tok")


def test_job_path_nested():
    assert jk._job_path("deploy") == "job/deploy"
    assert jk._job_path("platform/deploy-prod") == "job/platform/job/deploy-prod"
    assert jk._job_path("/platform/deploy/") == "job/platform/job/deploy"


def test_not_configured(monkeypatch):
    monkeypatch.setattr(get_settings(), "jenkins_url", None)
    assert "not configured" in jk.jenkins_job_status.invoke({"job": "x"})


def test_job_status_formatting(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(
        jk,
        "request_json",
        lambda *a, **k: HttpResult(
            ok=True, status=200,
            data={"number": 42, "result": "FAILURE", "building": False, "duration": 65000, "url": "u"},
        ),
    )
    out = jk.jenkins_job_status.invoke({"job": "platform/deploy"})
    assert "#42" in out and "FAILURE" in out and "65s" in out


def test_build_log_tails_and_redacts(monkeypatch):
    _enable(monkeypatch)
    log = "\n".join(f"line {i}" for i in range(300)) + "\npassword: hunter2"
    monkeypatch.setattr(jk, "request_json", lambda *a, **k: HttpResult(ok=True, status=200, data=log))
    out = jk.jenkins_build_log.invoke({"job": "deploy", "tail_lines": 10})
    assert "line 299" in out and "line 0" not in out
    assert "hunter2" not in out and "REDACTED" in out


def test_test_report_failures(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(
        jk,
        "request_json",
        lambda *a, **k: HttpResult(
            ok=True, status=200,
            data={
                "failCount": 1, "passCount": 10, "skipCount": 0,
                "suites": [{"cases": [
                    {"className": "FooTest", "name": "test_bar", "status": "FAILED", "errorDetails": "assert 1==2"},
                    {"className": "FooTest", "name": "test_ok", "status": "PASSED"},
                ]}],
            },
        ),
    )
    out = jk.jenkins_test_report.invoke({"job": "deploy"})
    assert "1 failed" in out and "FooTest.test_bar" in out and "assert 1==2" in out


def test_queue_formatting(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(
        jk,
        "request_json",
        lambda *a, **k: HttpResult(
            ok=True, status=200,
            data={"items": [{"task": {"name": "deploy"}, "why": "Waiting for next executor", "stuck": True}]},
        ),
    )
    out = jk.jenkins_queue.invoke({})
    assert "deploy" in out and "Waiting for next executor" in out and "STUCK" in out


def test_build_stages_failed(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(
        jk,
        "request_json",
        lambda *a, **k: HttpResult(
            ok=True, status=200,
            data={"status": "FAILED", "stages": [
                {"name": "Build", "status": "SUCCESS", "durationMillis": 1000},
                {"name": "Test", "status": "FAILED", "durationMillis": 2000},
            ]},
        ),
    )
    out = jk.jenkins_build_stages.invoke({"job": "deploy"})
    assert "Test: FAILED" in out and "failed/abnormal stage(s): Test" in out
