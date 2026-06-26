"""LLM factory.

Defaults to Claude Opus 4.8 through `langchain-anthropic` (which wraps the
official Anthropic SDK). Adaptive extended thinking is on by default — the
right mode for multi-step triage reasoning. Set DEVOPS_AGENT_LLM_PROVIDER=bedrock
to run the same model through Amazon Bedrock instead (install the `bedrock`
extra first).
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel

from .config import Settings


def build_llm(settings: Settings) -> BaseChatModel:
    if settings.llm_provider == "bedrock":
        return _build_bedrock(settings)
    if settings.llm_provider == "github":
        return _build_github(settings)
    return _build_anthropic(settings)


def _build_github(settings: Settings) -> BaseChatModel:
    """GitHub Models (OpenAI-compatible). Needs only a GitHub token with
    `models: read` — no Anthropic key or AWS access required."""
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "GitHub Models provider requested but langchain-openai is not installed. "
            "Install it with: uv sync --extra github"
        ) from exc

    if not settings.github_token:
        raise RuntimeError(
            "GitHub Models needs a token with the 'models: read' permission. Set "
            "GITHUB_MODELS_TOKEN (or GITHUB_TOKEN) to a GitHub personal access token."
        )
    # The global default model is a Claude id; pick a GitHub model instead.
    model = settings.github_model if settings.model.startswith("claude") else settings.model
    return ChatOpenAI(
        model=model,
        base_url=settings.github_models_url,
        api_key=settings.github_token,
        max_tokens=settings.max_tokens,
        timeout=settings.llm_timeout,
        max_retries=settings.llm_max_retries,
    )


def _build_anthropic(settings: Settings) -> BaseChatModel:
    from langchain_anthropic import ChatAnthropic

    kwargs: dict = {
        "model": settings.model,
        "max_tokens": settings.max_tokens,
        "timeout": settings.llm_timeout,
        "max_retries": settings.llm_max_retries,
    }
    if settings.thinking:
        # Opus 4.8 supports only adaptive thinking (a fixed budget_tokens 400s).
        kwargs["thinking"] = {"type": "adaptive"}
    try:
        return ChatAnthropic(**kwargs)
    except Exception:
        # Older langchain-anthropic builds may not accept the thinking kwarg.
        kwargs.pop("thinking", None)
        return ChatAnthropic(**kwargs)


def _build_bedrock(settings: Settings) -> BaseChatModel:
    try:
        from langchain_aws import ChatBedrockConverse
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "Bedrock provider requested but langchain-aws is not installed. "
            "Install it with: uv sync --extra bedrock"
        ) from exc

    model_id = settings.model
    if not model_id.startswith(("anthropic.", "us.", "eu.", "apac.")):
        # Bedrock model IDs carry a provider prefix; map the bare Anthropic id.
        model_id = f"anthropic.{model_id}"
    try:
        return ChatBedrockConverse(
            model=model_id,
            region_name=settings.aws_region,
            max_tokens=settings.max_tokens,
        )
    except Exception as exc:  # almost always missing/unresolvable AWS credentials
        raise RuntimeError(
            f"Could not initialize the Bedrock client for model {model_id!r} in region "
            f"{settings.aws_region}. Make sure AWS credentials are available to boto3 and that "
            "model access is enabled in the Bedrock console. If you use an SSO / login-session "
            'profile, export static credentials first: eval "$(aws configure export-credentials '
            '--format env)".'
        ) from exc
