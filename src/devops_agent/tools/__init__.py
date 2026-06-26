"""Tool registry.

`all_tools()` returns every tool the agent can call. As new tool modules are
added (Prometheus, Grafana, Datadog, AWS, Jenkins, Kafka, Redis, databases),
register them here. Keeping this in one place lets the CLI list capabilities and
lets us trim the surface per environment later if needed.
"""

from __future__ import annotations

from langchain_core.tools import BaseTool

from .aws import AWS_TOOLS
from .correlation import CORRELATION_TOOLS
from .databases import DATABASE_TOOLS
from .datadog import DATADOG_TOOLS
from .grafana import GRAFANA_TOOLS
from .helm import HELM_TOOLS
from .jenkins import JENKINS_TOOLS
from .k8s_network import K8S_NETWORK_TOOLS
from .kafka import KAFKA_TOOLS
from .kubernetes import KUBERNETES_TOOLS
from .network import NETWORK_TOOLS
from .prometheus import PROMETHEUS_TOOLS
from .redis import REDIS_TOOLS

_TOOL_GROUPS: dict[str, list[BaseTool]] = {
    "correlation": CORRELATION_TOOLS,
    "kubernetes": KUBERNETES_TOOLS,
    "helm": HELM_TOOLS,
    "network": NETWORK_TOOLS,
    "k8s_network": K8S_NETWORK_TOOLS,
    "prometheus": PROMETHEUS_TOOLS,
    "grafana": GRAFANA_TOOLS,
    "datadog": DATADOG_TOOLS,
    "aws": AWS_TOOLS,
    "jenkins": JENKINS_TOOLS,
    "kafka": KAFKA_TOOLS,
    "redis": REDIS_TOOLS,
    "databases": DATABASE_TOOLS,
}


def tool_groups() -> dict[str, list[BaseTool]]:
    return dict(_TOOL_GROUPS)


def all_tools() -> list[BaseTool]:
    tools: list[BaseTool] = []
    for group in _TOOL_GROUPS.values():
        tools.extend(group)
    return tools


def tools_for(names: list[str]) -> list[BaseTool]:
    """Return the tools for the named groups (for trimming the surface per env)."""
    unknown = [n for n in names if n not in _TOOL_GROUPS]
    if unknown:
        raise KeyError(f"unknown tool group(s): {', '.join(unknown)}. Available: {', '.join(_TOOL_GROUPS)}")
    selected: list[BaseTool] = []
    for n in names:
        selected.extend(_TOOL_GROUPS[n])
    return selected


__all__ = ["all_tools", "tool_groups", "tools_for"]
