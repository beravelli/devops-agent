"""Redis triage tools.

Reached by exec-ing `redis-cli` into a Redis pod (connecting to the local Redis
by default). Read-only diagnostics only: INFO, SLOWLOG, CLIENT LIST. No auth is
passed and no keys are written or read.
"""

from __future__ import annotations

from langchain_core.tools import tool

from .kexec import pod_exec

# INFO sections we permit; guards against passing arbitrary args to redis-cli.
_INFO_SECTIONS = {
    "", "server", "clients", "memory", "persistence", "stats", "replication",
    "cpu", "commandstats", "latencystats", "cluster", "keyspace", "errorstats",
    "everything", "default", "all",
}


def _redis_cli(host: str, port: int) -> list[str]:
    argv = ["redis-cli"]
    if host:
        argv += ["-h", host]
    if port:
        argv += ["-p", str(port)]
    return argv


@tool
def redis_info(pod: str, section: str = "", host: str = "", port: int = 0, namespace: str = "", container: str = "") -> str:
    """Run redis-cli INFO (optionally a single section) on a Redis pod.

    Use to check Redis health: memory usage and fragmentation (memory),
    connected/blocked clients (clients), hit rate and evictions (stats),
    or master/replica state and replication offset lag (replication).

    Args:
        pod: A Redis pod to exec into.
        section: INFO section, e.g. "memory", "clients", "stats", "replication". Empty = all.
        host: Redis host; empty = local instance in the pod.
        port: Redis port; 0 = default (6379).
        namespace: Pod namespace.
        container: Container name.
    """
    if section.lower() not in _INFO_SECTIONS:
        return f"Unsupported INFO section {section!r}. Allowed: {', '.join(sorted(s for s in _INFO_SECTIONS if s))}."
    argv = _redis_cli(host, port) + ["INFO"]
    if section:
        argv.append(section.lower())
    return pod_exec(pod, argv, namespace=namespace, container=container)


@tool
def redis_slowlog(pod: str, count: int = 20, host: str = "", port: int = 0, namespace: str = "", container: str = "") -> str:
    """Show the Redis slow-query log (SLOWLOG GET).

    Use when Redis latency is high — the slowlog reveals which commands exceeded
    the slowlog threshold and how long they took.

    Args:
        pod: A Redis pod to exec into.
        count: Number of recent slowlog entries to fetch.
        host: Redis host; empty = local.
        port: Redis port; 0 = default.
        namespace: Pod namespace.
        container: Container name.
    """
    argv = _redis_cli(host, port) + ["SLOWLOG", "GET", str(max(1, count))]
    return pod_exec(pod, argv, namespace=namespace, container=container)


@tool
def redis_clients(pod: str, host: str = "", port: int = 0, namespace: str = "", container: str = "") -> str:
    """List connected Redis clients (CLIENT LIST).

    Use to investigate connection exhaustion or a noisy client — shows each
    connection's address, age, idle time, and last command.

    Args:
        pod: A Redis pod to exec into.
        host: Redis host; empty = local.
        port: Redis port; 0 = default.
        namespace: Pod namespace.
        container: Container name.
    """
    argv = _redis_cli(host, port) + ["CLIENT", "LIST"]
    return pod_exec(pod, argv, namespace=namespace, container=container)


REDIS_TOOLS = [
    redis_info,
    redis_slowlog,
    redis_clients,
]
