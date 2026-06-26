"""DevOps triage agent: a LangChain tool-calling agent with hand-written
custom tools (no MCP) for triaging CI/CD, network, Kubernetes, Helm, AWS
EKS/EC2, and observability (Grafana / Prometheus / Datadog) issues."""

__version__ = "0.1.0"

from .config import Settings, get_settings

__all__ = ["Settings", "get_settings", "__version__"]
