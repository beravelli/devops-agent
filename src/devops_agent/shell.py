"""Safe subprocess execution shared by all CLI-backed tools.

Tools never call `subprocess` directly — they go through `run_command`, which
gives us one place to enforce timeouts, capture structured output, and avoid
shell injection (commands are always argv lists, never a shell string).
"""

from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass


@dataclass
class CommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


def run_command(
    cmd: list[str],
    timeout: int = 60,
    input_text: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> CommandResult:
    """Run an argv list and capture its output. Never raises on command failure;
    callers inspect the returned `CommandResult`."""
    printable = " ".join(shlex.quote(c) for c in cmd)
    env = None
    if extra_env:
        env = {**os.environ, **extra_env}
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            input=input_text,
            env=env,
        )
        return CommandResult(
            command=printable,
            returncode=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
        )
    except FileNotFoundError:
        return CommandResult(
            command=printable,
            returncode=127,
            stdout="",
            stderr=f"executable not found: {cmd[0]!r} (is it installed and on PATH?)",
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            command=printable,
            returncode=124,
            stdout=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
            stderr=f"command timed out after {timeout}s",
            timed_out=True,
        )
