"""Tests for in-cluster network triage tools (kubectl + exec stubbed)."""

from __future__ import annotations

import devops_agent.tools.k8s_network as net


def test_get_endpoints_builds_command(monkeypatch):
    captured = {}
    monkeypatch.setattr(net, "cli_tool_output", lambda cmd, *a, **k: captured.update(cmd=cmd) or "ok")
    net.k8s_get_endpoints.invoke({"service": "redis", "namespace": "cache"})
    cmd = captured["cmd"]
    assert cmd[0] == "kubectl"
    assert "get" in cmd and "endpoints" in cmd and "redis" in cmd
    assert "cache" in cmd  # namespace flag


def test_describe_networkpolicy_builds_command(monkeypatch):
    captured = {}
    monkeypatch.setattr(net, "cli_tool_output", lambda cmd, *a, **k: captured.update(cmd=cmd) or "ok")
    net.k8s_describe_networkpolicy.invoke({"name": "deny-all", "namespace": "prod"})
    cmd = captured["cmd"]
    assert "describe" in cmd and "networkpolicy" in cmd and "deny-all" in cmd


def test_dns_check_validates_hostname(monkeypatch):
    monkeypatch.setattr(net, "pod_exec", lambda *a, **k: "ran")
    assert "Invalid hostname" in net.k8s_pod_dns_check.invoke({"pod": "p", "hostname": "redis; rm -rf /"})


def test_dns_check_argv(monkeypatch):
    captured = {}
    monkeypatch.setattr(net, "pod_exec", lambda pod, argv, **k: captured.update(pod=pod, argv=argv) or "ok")
    net.k8s_pod_dns_check.invoke({"pod": "app-0", "hostname": "redis.cache.svc.cluster.local"})
    assert captured["argv"] == ["getent", "hosts", "redis.cache.svc.cluster.local"]


def test_connect_check_validates(monkeypatch):
    monkeypatch.setattr(net, "pod_exec", lambda *a, **k: "ran")
    assert "Invalid host" in net.k8s_pod_connect_check.invoke({"pod": "p", "host": "a b", "port": 80})
    assert "port must be" in net.k8s_pod_connect_check.invoke({"pod": "p", "host": "redis", "port": 99999})


def test_connect_check_argv(monkeypatch):
    captured = {}
    monkeypatch.setattr(net, "pod_exec", lambda pod, argv, **k: captured.update(argv=argv) or "ok")
    net.k8s_pod_connect_check.invoke({"pod": "app-0", "host": "redis", "port": 6379})
    argv = captured["argv"]
    assert argv[0] == "python3" and argv[1] == "-c"
    assert argv[-2:] == ["redis", "6379"]
    assert "socket" in argv[2]
