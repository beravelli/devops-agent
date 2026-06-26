"""Tests for the hosted-service tools (Kafka, Redis, databases) and the guarded
pod-exec helper. No real cluster is touched — exec is stubbed."""

from __future__ import annotations

import devops_agent.tools.databases as db
import devops_agent.tools.kafka as kafka
import devops_agent.tools.kexec as kexec
import devops_agent.tools.redis as redis
from devops_agent.config import get_settings
from devops_agent.shell import CommandResult


# --- read-only SQL guard ----------------------------------------------------


def test_is_readonly_sql_allows_reads():
    assert db.is_readonly_sql("SELECT 1")
    assert db.is_readonly_sql("select * from t where id = 5")
    assert db.is_readonly_sql("SHOW processlist")
    assert db.is_readonly_sql("WITH a AS (SELECT 1) SELECT * FROM a")
    assert db.is_readonly_sql("EXPLAIN SELECT * FROM t")
    assert db.is_readonly_sql("SELECT set_config('x','y',true)")  # set_config != SET keyword


def test_is_readonly_sql_blocks_writes_and_stacked():
    assert not db.is_readonly_sql("DELETE FROM t")
    assert not db.is_readonly_sql("UPDATE t SET x = 1")
    assert not db.is_readonly_sql("SELECT 1; DROP TABLE t")
    assert not db.is_readonly_sql("WITH a AS (INSERT INTO t VALUES (1) RETURNING *) SELECT * FROM a")
    assert not db.is_readonly_sql("TRUNCATE t")
    assert not db.is_readonly_sql("SELECT * INTO newt FROM t")
    assert not db.is_readonly_sql("")


def test_db_query_blocks_write(monkeypatch):
    monkeypatch.setattr(db, "pod_exec", lambda *a, **k: "should not run")
    out = db.db_query.invoke({"pod": "p", "engine": "postgres", "query": "DELETE FROM t"})
    assert "BLOCKED" in out


def test_db_query_builds_psql_argv(monkeypatch):
    captured = {}

    def fake_exec(pod, argv, **k):
        captured["pod"] = pod
        captured["argv"] = argv
        return "ok"

    monkeypatch.setattr(db, "pod_exec", fake_exec)
    db.db_query.invoke({"pod": "pg-0", "engine": "postgres", "query": "SELECT 1", "database": "app"})
    assert captured["pod"] == "pg-0"
    assert captured["argv"][0] == "psql"
    assert "SET default_transaction_read_only TO on" in captured["argv"]
    assert captured["argv"][-1] == "SELECT 1"
    assert "-d" in captured["argv"] and "app" in captured["argv"]


def test_db_query_rejects_bad_engine(monkeypatch):
    monkeypatch.setattr(db, "pod_exec", lambda *a, **k: "x")
    assert "engine must be" in db.db_query.invoke({"pod": "p", "engine": "oracle", "query": "SELECT 1"})


# --- pod_exec helper --------------------------------------------------------


def test_pod_exec_blocked_when_disabled(monkeypatch):
    monkeypatch.setattr(get_settings(), "allow_exec", False)
    assert "BLOCKED" in kexec.pod_exec("p", ["redis-cli", "INFO"])


def test_pod_exec_builds_command(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "allow_exec", True)
    monkeypatch.setattr(s, "kube_context", None)
    monkeypatch.setattr(s, "kube_namespace", None)
    captured = {}

    def fake_run(cmd, **k):
        captured["cmd"] = cmd
        return CommandResult(command=" ".join(cmd), returncode=0, stdout="out", stderr="")

    monkeypatch.setattr(kexec, "run_command", fake_run)
    kexec.pod_exec("redis-0", ["redis-cli", "INFO", "memory"], namespace="cache", container="redis")
    cmd = captured["cmd"]
    assert cmd[:1] == ["kubectl"]
    assert "exec" in cmd and "redis-0" in cmd
    assert cmd[-4:] == ["--", "redis-cli", "INFO", "memory"]
    assert "-n" in cmd and "cache" in cmd and "-c" in cmd and "redis" in cmd


# --- kafka / redis argv -----------------------------------------------------


def test_kafka_consumer_group_lag_argv(monkeypatch):
    captured = {}
    monkeypatch.setattr(kafka, "pod_exec", lambda pod, argv, **k: captured.update(pod=pod, argv=argv) or "ok")
    kafka.kafka_consumer_group_lag.invoke({"pod": "kafka-0", "group": "billing"})
    assert captured["argv"] == [
        "kafka-consumer-groups.sh", "--bootstrap-server", "localhost:9092", "--describe", "--group", "billing"
    ]


def test_redis_info_rejects_bad_section(monkeypatch):
    monkeypatch.setattr(redis, "pod_exec", lambda *a, **k: "ran")
    out = redis.redis_info.invoke({"pod": "r", "section": "; rm -rf"})
    assert "Unsupported INFO section" in out


def test_redis_info_argv(monkeypatch):
    captured = {}
    monkeypatch.setattr(redis, "pod_exec", lambda pod, argv, **k: captured.update(argv=argv) or "ok")
    redis.redis_info.invoke({"pod": "r-0", "section": "memory", "port": 6380})
    assert captured["argv"] == ["redis-cli", "-p", "6380", "INFO", "memory"]
