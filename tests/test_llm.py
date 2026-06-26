"""Tests for the LLM provider factory (construction only — no network)."""

from __future__ import annotations

import pytest

from devops_agent.config import Settings
from devops_agent.llm import build_llm


def _github_settings(**over) -> Settings:
    s = Settings()
    s.llm_provider = "github"
    s.github_token = "ghp_dummy"
    s.model = "claude-opus-4-8"  # the global default
    for k, v in over.items():
        setattr(s, k, v)
    return s


def test_github_provider_builds_openai_client():
    llm = build_llm(_github_settings())
    assert type(llm).__name__ == "ChatOpenAI"
    # Claude default is substituted for a GitHub model
    assert llm.model_name == "openai/gpt-4o"
    assert "models.github.ai" in str(llm.openai_api_base)


def test_github_provider_honors_explicit_model():
    llm = build_llm(_github_settings(model="openai/gpt-4o-mini"))
    assert llm.model_name == "openai/gpt-4o-mini"


def test_github_provider_requires_token():
    s = _github_settings(github_token=None)
    with pytest.raises(RuntimeError, match="models: read"):
        build_llm(s)
