"""Kubernetes triage tools (read-only kubectl wrappers).

These cover the first things you reach for when a workload on EKS misbehaves:
what pods exist and their state, why a pod won't start (describe + events),
what the logs say, and whether nodes/pods are resource-starved.
"""

from __future__ import annotations

from langchain_core.tools import tool

from ..config import get_settings
from .base import cli_tool_output

_SECRET_TYPES = {"secret", "secrets"}


def _kubectl(args: list[str], namespace: str | None = None, all_namespaces: bool = False) -> list[str]:
    settings = get_settings()
    # --context is a true kubectl global flag and goes before the subcommand.
    # --namespace is NOT — placing it before the verb triggers "flags cannot be
    # placed before plugin name" on some kubectl builds.  We append it after
    # the verb args instead, and skip it entirely when --all-namespaces is set.
    cmd = ["kubectl", *settings.kubectl_context_flags()] + args
    if all_namespaces:
        cmd.append("--all-namespaces")
    else:
        ns = namespace or settings.kube_namespace or None
        if ns:
            cmd += ["--namespace", ns]
    return cmd


@tool
def k8s_get_pods(namespace: str = "", selector: str = "", all_namespaces: bool = False) -> str:
    """List pods and their status, restarts, and node placement (kubectl get pods -o wide).

    Use this first when triaging a workload issue to see which pods are
    CrashLoopBackOff, Pending, ImagePullBackOff, OOMKilled, or Evicted.

    Args:
        namespace: Namespace to query. Empty uses the configured default.
        selector: Optional label selector, e.g. "app=payments".
        all_namespaces: List pods across every namespace.
    """
    args = ["get", "pods", "-o", "wide"]
    if selector:
        args += ["-l", selector]
    return cli_tool_output(_kubectl(args, namespace or None, all_namespaces))


@tool
def k8s_describe(kind: str, name: str, namespace: str = "") -> str:
    """Describe a Kubernetes object, including its events (kubectl describe).

    The single most useful tool for "why won't this start / why is it unhealthy":
    shows conditions, recent events, probe failures, scheduling problems, and
    container restart reasons.

    Args:
        kind: Resource kind, e.g. pod, deployment, statefulset, node, service, ingress, pvc.
        name: Object name.
        namespace: Namespace (ignored for cluster-scoped kinds like node).
    """
    return cli_tool_output(_kubectl(["describe", kind, name], namespace or None))


@tool
def k8s_logs(
    pod: str,
    namespace: str = "",
    container: str = "",
    tail: int = 200,
    previous: bool = False,
    since: str = "",
) -> str:
    """Fetch logs from a pod (kubectl logs).

    Use after k8s_get_pods identifies a failing pod. Set previous=true to read
    the logs of the last crashed container (essential for CrashLoopBackOff).

    Args:
        pod: Pod name.
        namespace: Namespace. Empty uses the configured default.
        container: Container name (required for multi-container pods).
        tail: Number of trailing lines to return.
        previous: Read the previous (crashed) container instance's logs.
        since: Relative window, e.g. "15m" or "1h".
    """
    args = ["logs", pod, f"--tail={tail}"]
    if container:
        args += ["-c", container]
    if previous:
        args.append("--previous")
    if since:
        args.append(f"--since={since}")
    return cli_tool_output(_kubectl(args, namespace or None))


@tool
def k8s_get_events(namespace: str = "", all_namespaces: bool = False) -> str:
    """List recent cluster events, newest last (kubectl get events).

    Use to spot scheduling failures, image pull errors, volume mount problems,
    and node pressure across a namespace.

    Args:
        namespace: Namespace to query. Empty uses the configured default.
        all_namespaces: Events across every namespace.
    """
    args = ["get", "events", "--sort-by=.lastTimestamp"]
    return cli_tool_output(_kubectl(args, namespace or None, all_namespaces))


@tool
def k8s_top_pods(namespace: str = "", all_namespaces: bool = False) -> str:
    """Show pod CPU/memory usage (kubectl top pods). Requires metrics-server.

    Use to confirm whether a pod is resource-starved or to find the noisy
    neighbour driving node pressure.

    Args:
        namespace: Namespace to query. Empty uses the configured default.
        all_namespaces: Usage across every namespace.
    """
    return cli_tool_output(_kubectl(["top", "pods"], namespace or None, all_namespaces))


@tool
def k8s_top_nodes() -> str:
    """Show node CPU/memory usage (kubectl top nodes). Requires metrics-server.

    Use to find saturated nodes when pods are being evicted or throttled.
    """
    return cli_tool_output(_kubectl(["top", "nodes"]))


@tool
def k8s_get_nodes() -> str:
    """List nodes with status, roles, version, and pressure conditions (kubectl get nodes -o wide).

    Use when pods are Pending or being evicted, to check for NotReady, disk/memory
    pressure, or capacity issues on the EKS node groups.
    """
    return cli_tool_output(_kubectl(["get", "nodes", "-o", "wide"]))


@tool
def k8s_get_resource(
    kind: str, name: str = "", namespace: str = "", output: str = "yaml", selector: str = ""
) -> str:
    """Get the manifest/spec of a resource (kubectl get -o yaml|json|wide).

    Use to inspect a deployment's image/env/resources, a service's selectors and
    endpoints, an ingress's rules, or a HPA's targets. Reading raw Secret values
    is refused — use k8s_describe on the secret to see its keys instead.

    Args:
        kind: Resource kind (deployment, service, ingress, configmap, hpa, pvc, ...).
        name: Object name. Empty lists all of that kind.
        namespace: Namespace. Empty uses the configured default.
        output: Output format: yaml, json, or wide.
        selector: Optional label selector when listing.
    """
    if kind.lower() in _SECRET_TYPES and output in {"yaml", "json"}:
        return (
            "BLOCKED: refusing to dump raw Secret values. Use k8s_describe(kind='secret', "
            "name=...) to see the secret's keys and metadata without exposing values."
        )
    args = ["get", kind]
    if name:
        args.append(name)
    if selector:
        args += ["-l", selector]
    args += ["-o", output]
    return cli_tool_output(_kubectl(args, namespace or None))


@tool
def k8s_rollout_status(kind: str, name: str, namespace: str = "") -> str:
    """Check rollout progress/health of a deployment, statefulset, or daemonset.

    Use to confirm whether a recent deploy actually rolled out or is stuck.

    Args:
        kind: deployment, statefulset, or daemonset.
        name: Object name.
        namespace: Namespace. Empty uses the configured default.
    """
    return cli_tool_output(
        _kubectl(["rollout", "status", f"{kind}/{name}", "--timeout=10s"], namespace or None)
    )


KUBERNETES_TOOLS = [
    k8s_get_pods,
    k8s_describe,
    k8s_logs,
    k8s_get_events,
    k8s_top_pods,
    k8s_top_nodes,
    k8s_get_nodes,
    k8s_get_resource,
    k8s_rollout_status,
]
