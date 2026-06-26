"""Agent construction + hardening tests.

The build_agent test is a real regression guard: it exercises the
`langchain.agents` import path (AgentExecutor / create_tool_calling_agent),
which a langchain major-version bump silently broke once. It uses the GitHub
provider with a dummy token so no network or real credential is needed —
ChatOpenAI and the agent graph construct entirely offline."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from devops_agent.agent import TriageResult, build_agent
from devops_agent.config import Settings
from devops_agent.tools import all_tools, tools_for


def _settings(**over) -> Settings:
    s = Settings()
    s.llm_provider = "github"
    s.github_token = "ghp_dummy"
    for k, v in over.items():
        setattr(s, k, v)
    return s


def test_build_agent_constructs_with_all_tools():
    # Explicitly clear tool_groups so a .env with DEVOPS_AGENT_TOOL_GROUPS set
    # doesn't cause the agent to load only a subset of tools.
    ex = build_agent(_settings(tool_groups=None))
    assert type(ex).__name__ == "AgentExecutor"
    assert len(ex.tools) == len(all_tools())


def test_build_agent_honors_tool_group_trimming():
    ex = build_agent(_settings(tool_groups="kubernetes,helm"))
    expected = len(tools_for(["kubernetes", "helm"]))
    assert len(ex.tools) == expected
    assert expected < len(all_tools())


def test_tools_for_rejects_unknown_group():
    with pytest.raises(KeyError):
        tools_for(["kubernetes", "not_a_group"])


def test_triage_result_to_dict():
    action = SimpleNamespace(tool="k8s_get_pods", tool_input={"namespace": "prod"})
    result = TriageResult(output="all good", steps=[(action, "pod list output")])
    d = result.to_dict()
    assert d["report"] == "all good"
    assert d["steps"][0]["tool"] == "k8s_get_pods"
    assert d["steps"][0]["input"] == {"namespace": "prod"}
    assert d["steps"][0]["observation"] == "pod list output"
