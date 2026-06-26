"""Central configuration, loaded from environment / `.env`.

Everything is optional except an LLM credential. Integration settings (URLs,
tokens) default to empty; the tools that depend on them report "not
configured" rather than failing hard, so the agent degrades gracefully in
environments where only some backends are reachable.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DEVOPS_AGENT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # --- LLM -----------------------------------------------------------------
    llm_provider: str = "anthropic"  # "anthropic" | "bedrock" | "github"
    model: str = "claude-opus-4-8"
    max_tokens: int = 8000
    thinking: bool = True
    llm_timeout: float = 600.0
    llm_max_retries: int = 2

    # GitHub Models (OpenAI-compatible) — used when llm_provider == "github".
    # Lets you run the agent with only a GitHub token (no Anthropic key / AWS).
    github_models_url: str = "https://models.github.ai/inference"
    github_model: str = "openai/gpt-4o"
    github_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "DEVOPS_AGENT_GITHUB_TOKEN", "GITHUB_MODELS_TOKEN", "GITHUB_TOKEN"
        ),
    )

    # --- Safety --------------------------------------------------------------
    allow_mutations: bool = False
    # Allow `kubectl exec` of constrained, read-only client commands (redis-cli
    # INFO, kafka-consumer-groups --describe, read-only SQL) for service triage.
    # Separate from allow_mutations; set false to forbid all exec.
    allow_exec: bool = True
    command_timeout: int = 60
    http_timeout: float = 30.0
    max_output_chars: int = 20000

    # --- Agent loop ----------------------------------------------------------
    max_iterations: int = 25
    verbose: bool = False
    # Comma-separated tool groups to expose (e.g. "kubernetes,helm,prometheus").
    # Empty = all groups. Trims the tool surface for a focused environment.
    tool_groups: str | None = None

    def selected_groups(self) -> list[str] | None:
        if not self.tool_groups:
            return None
        return [g.strip() for g in self.tool_groups.split(",") if g.strip()]

    # --- Kubernetes / Helm ---------------------------------------------------
    kube_context: str | None = None
    kube_namespace: str | None = None

    # --- AWS -----------------------------------------------------------------
    aws_region: str = Field(
        default="us-east-1",
        validation_alias=AliasChoices("DEVOPS_AGENT_AWS_REGION", "AWS_REGION"),
    )
    aws_profile: str | None = None

    # --- Prometheus ----------------------------------------------------------
    prometheus_url: str | None = None
    prometheus_token: str | None = None

    # --- Grafana -------------------------------------------------------------
    grafana_url: str | None = None
    grafana_token: str | None = None

    # --- Datadog -------------------------------------------------------------
    datadog_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DEVOPS_AGENT_DATADOG_API_KEY", "DD_API_KEY"),
    )
    datadog_app_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DEVOPS_AGENT_DATADOG_APP_KEY", "DD_APP_KEY"),
    )
    datadog_site: str = "datadoghq.com"

    # --- CI/CD (Jenkins) -----------------------------------------------------
    jenkins_url: str | None = None
    jenkins_user: str | None = None
    jenkins_token: str | None = None

    # ------------------------------------------------------------------------
    def kubectl_context_flags(self) -> list[str]:
        """Only the --context flag — safe to place before the subcommand."""
        return ["--context", self.kube_context] if self.kube_context else []

    def kubectl_global_flags(self) -> list[str]:
        """Context flag only. Namespace is intentionally omitted here because
        --namespace is not a true kubectl global flag and conflicts with
        --all-namespaces when placed before the subcommand."""
        return self.kubectl_context_flags()

    def aws_global_flags(self) -> list[str]:
        flags = ["--region", self.aws_region]
        if self.aws_profile:
            flags += ["--profile", self.aws_profile]
        return flags


@lru_cache
def get_settings() -> Settings:
    return Settings()
