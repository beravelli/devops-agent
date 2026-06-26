"""Network triage tools.

Pure-Python checks (DNS, TCP connect, HTTP) plus a couple of CLI fallbacks
(ping, traceroute). These run from wherever the agent runs, so they answer
"can *this* host reach the target" — pair them with k8s exec-based checks (added
in a later tool module) to test reachability from inside the cluster.
"""

from __future__ import annotations

import socket
import time

import httpx
from langchain_core.tools import tool

from ..config import get_settings
from .base import cli_tool_output


@tool
def dns_lookup(hostname: str) -> str:
    """Resolve a hostname to its IP addresses (A/AAAA records).

    Use first when a service is "unreachable" — a resolution failure or a stale
    record points at DNS rather than the service itself.

    Args:
        hostname: The hostname to resolve, e.g. "kafka.internal.example.com".
    """
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        return f"DNS resolution FAILED for {hostname!r}: {exc}"
    addrs = sorted({info[4][0] for info in infos})
    return f"{hostname} resolves to: " + ", ".join(addrs)


@tool
def tcp_check(host: str, port: int, timeout: float = 5.0) -> str:
    """Test whether a TCP port is open and accepting connections.

    Use to confirm L4 reachability of a backend (Redis 6379, Postgres 5432,
    Kafka 9092, an HTTPS endpoint 443) before blaming the application.

    Args:
        host: Hostname or IP.
        port: TCP port number.
        timeout: Connection timeout in seconds.
    """
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            elapsed = (time.perf_counter() - start) * 1000
            return f"OPEN: TCP {host}:{port} connected in {elapsed:.0f} ms"
    except OSError as exc:
        elapsed = (time.perf_counter() - start) * 1000
        return f"CLOSED/UNREACHABLE: TCP {host}:{port} failed after {elapsed:.0f} ms — {exc}"


@tool
def http_check(url: str, method: str = "GET", timeout: float = 10.0, verify_tls: bool = True) -> str:
    """Make an HTTP request and report status, latency, and key headers.

    Use to check an endpoint/health URL/ingress: distinguishes DNS failure,
    connection refused, TLS errors, timeouts, and HTTP error codes from each other.

    Args:
        url: Full URL, e.g. "https://api.example.com/healthz".
        method: HTTP method (GET, HEAD, ...).
        timeout: Request timeout in seconds.
        verify_tls: Set false to test past a TLS/cert problem (diagnostic only).
    """
    start = time.perf_counter()
    try:
        with httpx.Client(timeout=timeout, verify=verify_tls, follow_redirects=True) as client:
            resp = client.request(method, url)
    except httpx.HTTPError as exc:
        elapsed = (time.perf_counter() - start) * 1000
        return f"REQUEST FAILED for {url} after {elapsed:.0f} ms: {type(exc).__name__}: {exc}"
    elapsed = (time.perf_counter() - start) * 1000
    interesting = {
        k: v
        for k, v in resp.headers.items()
        if k.lower() in {"server", "content-type", "x-request-id", "retry-after", "location"}
    }
    header_lines = "\n".join(f"  {k}: {v}" for k, v in interesting.items())
    return (
        f"{method} {url}\n"
        f"status: {resp.status_code} {resp.reason_phrase}\n"
        f"latency: {elapsed:.0f} ms\n"
        f"final_url: {resp.url}\n"
        f"headers:\n{header_lines}"
    )


@tool
def ping_host(host: str, count: int = 4) -> str:
    """Send ICMP echo requests to measure reachability and latency (ping).

    Use for a quick L3 reachability/latency signal. Note many cloud security
    groups drop ICMP, so a failed ping does not by itself prove unreachability —
    confirm with tcp_check on a real port.

    Args:
        host: Hostname or IP.
        count: Number of echo requests.
    """
    settings = get_settings()
    return cli_tool_output(["ping", "-c", str(count), "-W", "2", host], settings)


@tool
def traceroute_host(host: str, max_hops: int = 20) -> str:
    """Trace the network path to a host (traceroute).

    Use to localize where connectivity breaks (which hop) for cross-VPC or
    on-prem connectivity issues. May be unavailable on minimal images.

    Args:
        host: Hostname or IP.
        max_hops: Maximum number of hops to probe.
    """
    settings = get_settings()
    return cli_tool_output(["traceroute", "-m", str(max_hops), "-w", "2", host], settings)


NETWORK_TOOLS = [
    dns_lookup,
    tcp_check,
    http_check,
    ping_host,
    traceroute_host,
]
