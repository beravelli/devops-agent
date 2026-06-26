"""Shared helpers for building tools.

`cli_tool_output` is the common path for any tool that shells out to a CLI
(kubectl, helm, aws, ...). It applies the read-only guardrail, runs the command
with a timeout, and returns redacted, truncated output ready to hand to the LLM.
"""

from __future__ import annotations

from ..config import Settings, get_settings
from ..safety import MutationBlocked, assert_readonly, format_result
from ..shell import run_command


def cli_tool_output(
    cmd: list[str],
    settings: Settings | None = None,
    input_text: str | None = None,
) -> str:
    settings = settings or get_settings()
    try:
        assert_readonly(cmd, settings.allow_mutations)
    except MutationBlocked as exc:
        return f"BLOCKED: {exc}"
    result = run_command(
        cmd,
        timeout=settings.command_timeout,
        input_text=input_text,
    )
    return format_result(result, max_chars=settings.max_output_chars)


def not_configured(backend: str, *env_vars: str) -> str:
    joined = ", ".join(env_vars)
    return (
        f"{backend} is not configured. Set {joined} in the environment (or .env) "
        f"to enable this tool."
    )
