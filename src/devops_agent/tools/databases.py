"""Database triage tools (Postgres / MySQL), read-only.

Reached by exec-ing the DB client (`psql` / `mysql`) into a pod that can connect
to the database. Every query is validated to be read-only (single SELECT / SHOW /
EXPLAIN / WITH, no DML/DDL, no stacked statements), and Postgres additionally runs
inside a `default_transaction_read_only` session as a server-side backstop.

No passwords are passed by these tools — rely on the exec'd pod's own auth (peer
auth on the DB pod, a configured `.pgpass`/`my.cnf`, or IAM).
"""

from __future__ import annotations

import re

from langchain_core.tools import tool

from .kexec import pod_exec

_READ_VERBS = {"select", "show", "explain", "with", "table", "values", "describe", "desc"}
_FORBIDDEN = {
    "insert", "update", "delete", "drop", "alter", "create", "truncate", "grant",
    "revoke", "copy", "call", "do", "merge", "vacuum", "reindex", "refresh",
    "lock", "comment", "set", "begin", "commit", "rollback", "into",
}


def is_readonly_sql(query: str) -> bool:
    """True only if `query` is a single read-only statement."""
    q = query.strip().rstrip(";").strip()
    if not q or ";" in q:  # reject empty and stacked statements
        return False
    first = q.split(None, 1)[0].lower()
    if first not in _READ_VERBS:
        return False
    lowered = q.lower()
    return not any(re.search(rf"\b{kw}\b", lowered) for kw in _FORBIDDEN)


def _psql_argv(query: str, host: str, port: int, user: str, database: str) -> list[str]:
    argv = ["psql"]
    if host:
        argv += ["-h", host]
    if port:
        argv += ["-p", str(port)]
    if user:
        argv += ["-U", user]
    if database:
        argv += ["-d", database]
    # -X ignore startup file, -tA tuples-only/unaligned; RO transaction as backstop.
    argv += ["-XtA", "-c", "SET default_transaction_read_only TO on", "-c", query]
    return argv


def _mysql_argv(query: str, host: str, port: int, user: str, database: str) -> list[str]:
    argv = ["mysql", "--batch"]
    if host:
        argv += ["-h", host]
    if port:
        argv += ["-P", str(port)]
    if user:
        argv += ["-u", user]
    if database:
        argv.append(database)
    argv += ["-e", query]
    return argv


@tool
def db_check_connection(
    pod: str, engine: str, host: str = "", port: int = 0, user: str = "", database: str = "", namespace: str = "", container: str = ""
) -> str:
    """Test database connectivity from a pod by running `SELECT 1`.

    Use to confirm the app's database is reachable and accepting connections
    before blaming the app — distinguishes "DB down / auth / network" from a
    query-level problem.

    Args:
        pod: A pod with the DB client that can reach the database.
        engine: "postgres" or "mysql".
        host: DB host; empty connects to the local instance in the pod.
        port: DB port; 0 = engine default.
        user: DB user.
        database: Database name.
        namespace: Pod namespace.
        container: Container name.
    """
    return _query_via_pod(pod, engine, "SELECT 1", host, port, user, database, namespace, container)


@tool
def db_query(
    pod: str, engine: str, query: str, host: str = "", port: int = 0, user: str = "", database: str = "", namespace: str = "", container: str = ""
) -> str:
    """Run a single READ-ONLY SQL query (SELECT / SHOW / EXPLAIN) via a pod.

    Use for ad-hoc read-only diagnostics: row counts, lock waits, replication
    lag, slow-query inspection. Writes and multi-statement queries are refused.

    Args:
        pod: A pod with the DB client that can reach the database.
        engine: "postgres" or "mysql".
        query: A single read-only SQL statement.
        host: DB host; empty = local.
        port: DB port; 0 = engine default.
        user: DB user.
        database: Database name.
        namespace: Pod namespace.
        container: Container name.
    """
    return _query_via_pod(pod, engine, query, host, port, user, database, namespace, container)


@tool
def pg_stat_activity(
    pod: str, host: str = "", port: int = 0, user: str = "", database: str = "", namespace: str = "", container: str = ""
) -> str:
    """Show active (non-idle) Postgres sessions ordered by how long they've run.

    Use to find long-running or stuck queries, lock waits, and connection
    pressure on a Postgres database.

    Args:
        pod: A pod with psql that can reach the database.
        host: DB host; empty = local.
        port: DB port; 0 = default (5432).
        user: DB user.
        database: Database name.
        namespace: Pod namespace.
        container: Container name.
    """
    query = (
        "SELECT pid, usename, state, wait_event_type, "
        "now() - query_start AS running_for, left(query, 100) AS query "
        "FROM pg_stat_activity WHERE state <> 'idle' "
        "ORDER BY running_for DESC NULLS LAST LIMIT 25"
    )
    return _query_via_pod(pod, "postgres", query, host, port, user, database, namespace, container)


def _query_via_pod(pod, engine, query, host, port, user, database, namespace, container) -> str:
    engine = engine.lower()
    if engine not in {"postgres", "postgresql", "pg", "mysql"}:
        return "engine must be 'postgres' or 'mysql'."
    if not is_readonly_sql(query):
        return (
            "BLOCKED: only a single read-only statement is allowed "
            "(SELECT / SHOW / EXPLAIN / WITH), with no DML/DDL or stacked statements."
        )
    if engine == "mysql":
        argv = _mysql_argv(query, host, port, user, database)
    else:
        argv = _psql_argv(query, host, port, user, database)
    return pod_exec(pod, argv, namespace=namespace, container=container)


DATABASE_TOOLS = [
    db_check_connection,
    db_query,
    pg_stat_activity,
]
