"""In-cluster network triage.

Two kinds of tool:
  - Kubernetes-native (no exec): service endpoints, NetworkPolicies, ingress —
    these answer most "service unreachable" questions reliably.
  - In-pod probes (via guarded exec): resolve a name / open a TCP connection from
    *inside* a pod, to test what the application actually sees through CoreDNS and
    any NetworkPolicy. Best-effort — they depend on tools present in the pod image.
"""

from __future__ import annotations

import re

from langchain_core.tools import tool

from .base import cli_tool_output
from .kexec import pod_exec
from .kubernetes import _kubectl

# Conservative hostname/host validation before it ever reaches an exec'd command.
_HOST_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

_TCP_PROBE = (
    "import socket,sys\n"
    "h,p=sys.argv[1],int(sys.argv[2])\n"
    "s=socket.socket(); s.settimeout(5)\n"
    "try:\n"
    "    s.connect((h,p)); print(f'OPEN {h}:{p}')\n"
    "except Exception as e:\n"
    "    print(f'FAIL {h}:{p} {type(e).__name__}: {e}')\n"
    "finally:\n"
    "    s.close()\n"
)


# --- Kubernetes-native (no exec) --------------------------------------------


@tool
def k8s_get_endpoints(service: str = "", namespace: str = "", all_namespaces: bool = False) -> str:
    """Show the ready backend addresses behind a Service (kubectl get endpoints).

    The first thing to check when a Service is "unreachable": if ENDPOINTS is
    <none>, the Service has no ready pods behind it (selector mismatch, all pods
    failing readiness) — the problem is the workload, not the network.

    Args:
        service: Service name; empty lists all in the namespace.
        namespace: Namespace; empty uses the configured default.
        all_namespaces: List across every namespace.
    """
    args = ["get", "endpoints", "-o", "wide"]
    if service:
        args.insert(2, service)
    return cli_tool_output(_kubectl(args, namespace or None, all_namespaces))


@tool
def k8s_get_networkpolicies(namespace: str = "", all_namespaces: bool = False) -> str:
    """List NetworkPolicies and the pods they select (kubectl get networkpolicy).

    Use when traffic is being dropped with no application error — a NetworkPolicy
    may be denying the ingress/egress the client needs.

    Args:
        namespace: Namespace; empty uses the configured default.
        all_namespaces: List across every namespace.
    """
    return cli_tool_output(_kubectl(["get", "networkpolicy", "-o", "wide"], namespace or None, all_namespaces))


@tool
def k8s_describe_networkpolicy(name: str, namespace: str = "") -> str:
    """Describe a NetworkPolicy's pod selector and ingress/egress rules.

    Use after k8s_get_networkpolicies to see exactly which ports/peers a policy
    allows — to confirm whether it permits the traffic in question.

    Args:
        name: NetworkPolicy name.
        namespace: Namespace; empty uses the configured default.
    """
    return cli_tool_output(_kubectl(["describe", "networkpolicy", name], namespace or None))


@tool
def k8s_get_ingress(namespace: str = "", all_namespaces: bool = False) -> str:
    """List Ingresses with their hosts, address, and ports (kubectl get ingress).

    Use for north-south (external) routing issues — confirms the host rules and
    whether the ingress has an address/load balancer assigned.

    Args:
        namespace: Namespace; empty uses the configured default.
        all_namespaces: List across every namespace.
    """
    return cli_tool_output(_kubectl(["get", "ingress", "-o", "wide"], namespace or None, all_namespaces))


# --- In-pod probes (via guarded exec) ---------------------------------------


@tool
def k8s_pod_dns_check(pod: str, hostname: str, namespace: str = "", container: str = "") -> str:
    """Resolve a hostname from *inside* a pod (getent hosts), testing CoreDNS.

    Use to confirm whether the application itself can resolve a name — catches
    CoreDNS problems, wrong search domains, and ndots issues that a lookup from
    outside the cluster would miss. Requires `getent` in the pod image.

    Args:
        pod: Pod to run the lookup in.
        hostname: Name to resolve, e.g. "redis.cache.svc.cluster.local".
        namespace: Pod namespace; empty uses the configured default.
        container: Container name if the pod has multiple.
    """
    if not _HOST_RE.match(hostname):
        return f"Invalid hostname {hostname!r} (allowed: letters, digits, dot, dash, underscore)."
    return pod_exec(pod, ["getent", "hosts", hostname], namespace=namespace, container=container)


@tool
def k8s_pod_connect_check(pod: str, host: str, port: int, namespace: str = "", container: str = "") -> str:
    """Test a TCP connection from *inside* a pod (OPEN / FAIL with reason).

    Use to confirm whether the application can actually reach a dependency
    (Redis 6379, Postgres 5432, Kafka 9092, an HTTPS endpoint) through the
    cluster network and any NetworkPolicy. Requires `python3` in the pod image.

    Args:
        pod: Pod to run the probe in.
        host: Target host or IP.
        port: Target TCP port.
        namespace: Pod namespace; empty uses the configured default.
        container: Container name if the pod has multiple.
    """
    if not _HOST_RE.match(host):
        return f"Invalid host {host!r} (allowed: letters, digits, dot, dash, underscore)."
    if not 0 < port < 65536:
        return "port must be between 1 and 65535."
    return pod_exec(
        pod, ["python3", "-c", _TCP_PROBE, host, str(port)], namespace=namespace, container=container
    )


K8S_NETWORK_TOOLS = [
    k8s_get_endpoints,
    k8s_get_networkpolicies,
    k8s_describe_networkpolicy,
    k8s_get_ingress,
    k8s_pod_dns_check,
    k8s_pod_connect_check,
]
