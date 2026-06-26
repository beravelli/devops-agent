"""Tests for the safety guardrails — the part that must never regress, since it
is what keeps the agent from touching production state or leaking secrets."""

from __future__ import annotations

import pytest

from devops_agent.safety import MutationBlocked, assert_readonly, redact


@pytest.mark.parametrize(
    "cmd",
    [
        ["kubectl", "get", "pods"],
        ["kubectl", "describe", "pod", "x"],
        ["kubectl", "logs", "x", "--previous"],
        ["kubectl", "rollout", "status", "deploy/x"],
        ["kubectl", "rollout", "history", "deploy/x"],
        ["helm", "list"],
        ["helm", "history", "x"],
        ["aws", "ec2", "describe-instances"],
    ],
)
def test_readonly_commands_allowed(cmd):
    # Should not raise when mutations are disabled.
    assert_readonly(cmd, allow_mutations=False)


@pytest.mark.parametrize(
    "cmd",
    [
        ["kubectl", "delete", "pod", "x"],
        ["kubectl", "apply", "-f", "x.yaml"],
        ["kubectl", "scale", "deploy/x", "--replicas=0"],
        ["kubectl", "exec", "x", "--", "sh"],
        ["kubectl", "rollout", "restart", "deploy/x"],
        ["helm", "upgrade", "x", "chart"],
        ["helm", "rollback", "x", "1"],
        ["aws", "ec2", "terminate-instances", "--instance-ids", "i-123"],
    ],
)
def test_mutating_commands_blocked(cmd):
    with pytest.raises(MutationBlocked):
        assert_readonly(cmd, allow_mutations=False)


def test_mutations_allowed_when_opted_in():
    assert_readonly(["kubectl", "delete", "pod", "x"], allow_mutations=True)


def test_redact_masks_secrets():
    text = "password: hunter2\napi_key=AKIAIOSFODNN7EXAMPLE\ntoken: eyJhbG.payloadpart.signature99"
    out = redact(text)
    assert "hunter2" not in out
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert "REDACTED" in out


def test_redact_leaves_normal_text():
    text = "pods are CrashLoopBackOff in namespace prod"
    assert redact(text) == text
