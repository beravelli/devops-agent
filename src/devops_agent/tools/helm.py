"""Helm triage tools (read-only helm wrappers).

Covers the common Helm questions during an incident: what's installed and is it
healthy, what changed in the last release, and what values/manifests a release
actually rendered with.
"""

from __future__ import annotations

from langchain_core.tools import tool

from ..config import get_settings
from .base import cli_tool_output


def _helm(args: list[str], namespace: str | None = None, all_namespaces: bool = False) -> list[str]:
    settings = get_settings()
    cmd = ["helm"]
    if settings.kube_context:
        cmd += ["--kube-context", settings.kube_context]
    if all_namespaces:
        cmd.append("--all-namespaces")
    elif namespace or settings.kube_namespace:
        cmd += ["--namespace", namespace or settings.kube_namespace]
    return cmd + args


@tool
def helm_list(namespace: str = "", all_namespaces: bool = False) -> str:
    """List Helm releases with their status, chart version, and revision (helm list).

    Use to see which releases are deployed, failed, pending-upgrade, or
    pending-rollback in a namespace.

    Args:
        namespace: Namespace to query. Empty uses the configured default.
        all_namespaces: List releases across every namespace.
    """
    return cli_tool_output(_helm(["list", "-o", "table"], namespace or None, all_namespaces))


@tool
def helm_status(release: str, namespace: str = "") -> str:
    """Show the status of a Helm release, including notes and resources (helm status).

    Use to confirm a release's deployed state and see the resources it manages.

    Args:
        release: Release name.
        namespace: Namespace. Empty uses the configured default.
    """
    return cli_tool_output(_helm(["status", release], namespace or None))


@tool
def helm_history(release: str, namespace: str = "", max_revisions: int = 10) -> str:
    """Show the revision history of a release (helm history).

    The fastest way to answer "what changed and when" — shows each revision's
    status, chart version, and app version, so you can correlate an incident with
    a recent upgrade and identify a rollback target.

    Args:
        release: Release name.
        namespace: Namespace. Empty uses the configured default.
        max_revisions: How many recent revisions to show.
    """
    return cli_tool_output(
        _helm(["history", release, "--max", str(max_revisions), "-o", "table"], namespace or None)
    )


@tool
def helm_get_values(release: str, namespace: str = "", revision: int = 0) -> str:
    """Show the user-supplied values a release was rendered with (helm get values).

    Use to inspect the effective configuration of a release. Secret-looking
    values are redacted automatically.

    Args:
        release: Release name.
        namespace: Namespace. Empty uses the configured default.
        revision: Specific revision number; 0 means the current release.
    """
    args = ["get", "values", release]
    if revision:
        args += ["--revision", str(revision)]
    return cli_tool_output(_helm(args, namespace or None))


@tool
def helm_get_manifest(release: str, namespace: str = "", revision: int = 0) -> str:
    """Show the rendered Kubernetes manifests for a release (helm get manifest).

    Use to see exactly what objects a release applies — useful when a release
    looks healthy but the workload isn't behaving, to diff intent vs reality.

    Args:
        release: Release name.
        namespace: Namespace. Empty uses the configured default.
        revision: Specific revision number; 0 means the current release.
    """
    args = ["get", "manifest", release]
    if revision:
        args += ["--revision", str(revision)]
    return cli_tool_output(_helm(args, namespace or None))


HELM_TOOLS = [
    helm_list,
    helm_status,
    helm_history,
    helm_get_values,
    helm_get_manifest,
]
