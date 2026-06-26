"""Guardrails for a triage agent that touches production.

Two jobs:
  1. Keep the agent read-only by default. Mutating verbs (apply, delete, scale,
     restart, drain, upgrade, ...) are refused unless `allow_mutations` is set.
  2. Redact obvious secrets from command output before it reaches the model or
     the transcript, and refuse to dump raw Secret values outright.
"""

from __future__ import annotations

import re

from .shell import CommandResult


class MutationBlocked(RuntimeError):
    """Raised when a tool is asked to perform a state-changing action while
    mutations are disabled."""


# Sub-commands / verbs that change cluster or cloud state. Compared case-insensitively
# against the first non-flag token after the binary.
_MUTATING_VERBS = {
    # kubectl
    "apply", "create", "delete", "edit", "patch", "replace", "scale", "annotate",
    "label", "set", "rollout", "drain", "cordon", "uncordon", "taint", "exec",
    "cp", "attach", "port-forward", "expose", "autoscale", "evict",
    # helm
    "install", "uninstall", "upgrade", "rollback", "delete",
    # aws (write-ish verbs; describe/list/get are allowed)
    "terminate-instances", "stop-instances", "start-instances", "reboot-instances",
    "delete-cluster", "update-cluster-config", "delete-nodegroup",
}

# A handful of read-only kubectl verbs that contain "set"/"rollout" substrings we
# still want to allow (e.g. `rollout status`, `rollout history`).
_READONLY_ROLLOUT_SUBCOMMANDS = {"status", "history"}


def assert_readonly(cmd: list[str], allow_mutations: bool) -> None:
    """Raise `MutationBlocked` if `cmd` looks state-changing and mutations are off."""
    if allow_mutations:
        return
    if not cmd:
        return
    binary = cmd[0].rsplit("/", 1)[-1].lower()
    tokens = [t for t in cmd[1:] if not t.startswith("-")]
    if not tokens:
        return
    verb = tokens[0].lower()
    if verb == "rollout":
        sub = tokens[1].lower() if len(tokens) > 1 else ""
        if sub in _READONLY_ROLLOUT_SUBCOMMANDS:
            return
    # kubectl/helm put the verb first; aws puts it after the service name
    # (`aws ec2 terminate-instances`), so consider the second token there too.
    candidates = {verb}
    if binary == "aws" and len(tokens) > 1:
        candidates.add(tokens[1].lower())
    offending = candidates & _MUTATING_VERBS
    if offending:
        raise MutationBlocked(
            f"Refusing to run a state-changing command ({next(iter(offending))!r}). "
            "Set DEVOPS_AGENT_ALLOW_MUTATIONS=true to permit this, or propose the "
            "command to a human for review instead of executing it."
        )


# --- Secret redaction -------------------------------------------------------

_REDACTION_PATTERNS = [
    # key: value / key = value where the key name smells secret
    re.compile(
        r"(?i)(\b(?:pass(?:word)?|secret|token|api[_-]?key|access[_-]?key|"
        r"client[_-]?secret|private[_-]?key|bearer|authorization)\b\s*[:=]\s*)"
        r"(['\"]?)([^\s'\",}]+)(\2)"
    ),
    # AWS access key IDs
    re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"),
    # JWTs
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
]


def redact(text: str) -> str:
    """Mask secret-looking values in arbitrary command output."""
    out = text
    out = _REDACTION_PATTERNS[0].sub(lambda m: f"{m.group(1)}{m.group(2)}***REDACTED***{m.group(4)}", out)
    for pat in _REDACTION_PATTERNS[1:]:
        out = pat.sub("***REDACTED***", out)
    return out


def format_result(result: CommandResult, max_chars: int = 20000) -> str:
    """Render a `CommandResult` into a compact, redacted string for the model."""
    parts = [f"$ {result.command}", f"exit_code: {result.returncode}"]
    body = result.stdout.strip()
    err = result.stderr.strip()
    if body:
        parts.append("--- stdout ---\n" + body)
    if err:
        parts.append("--- stderr ---\n" + err)
    if not body and not err:
        parts.append("(no output)")
    text = redact("\n".join(parts))
    if len(text) > max_chars:
        head = max_chars - 200
        text = text[:head] + f"\n... [truncated {len(text) - head} chars; narrow the query]"
    return text
