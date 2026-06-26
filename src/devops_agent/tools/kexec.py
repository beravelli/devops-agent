"""Run a read-only client command inside a pod via `kubectl exec`.

Hosted services (Kafka, Redis, databases) are usually reached by exec-ing their
client into the service's pod. The generic kubectl `exec` verb is blocked by the
safety layer (it can run anything); this helper is the *constrained* path —
callers build a fixed read-only command (e.g. `redis-cli INFO`) and the inner
argv is never a free-form shell string.
"""

from __future__ import annotations

from ..config import get_settings
from ..safety import format_result
from ..shell import run_command


def pod_exec(
    pod: str,
    inner: list[str],
    *,
    namespace: str = "",
    container: str = "",
    timeout: int | None = None,
) -> str:
    """Exec `inner` (an argv list) inside `pod` and return formatted output.

    `inner` must be a read-only client invocation assembled by the caller — not
    user-provided shell. Honors the `allow_exec` safety toggle.
    """
    settings = get_settings()
    if not settings.allow_exec:
        return (
            "BLOCKED: kubectl exec is disabled (DEVOPS_AGENT_ALLOW_EXEC=false). "
            "Service triage tools need exec to run read-only client commands."
        )
    cmd = ["kubectl"]
    if settings.kube_context:
        cmd += ["--context", settings.kube_context]
    ns = namespace or settings.kube_namespace
    if ns:
        cmd += ["-n", ns]
    cmd += ["exec", pod]
    if container:
        cmd += ["-c", container]
    cmd += ["--", *inner]
    result = run_command(cmd, timeout=timeout or settings.command_timeout)
    return format_result(result, max_chars=settings.max_output_chars)
