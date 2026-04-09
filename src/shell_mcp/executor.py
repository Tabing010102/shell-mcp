"""Shell command execution with asyncio subprocess."""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
from dataclasses import dataclass


@dataclass
class CommandResult:
    """Result of a shell command execution."""

    status: str  # "success", "error", "timeout", "killed"
    exit_code: int | None
    stdout: str
    stderr: str
    execution_time: float
    truncated: bool
    command: str


async def execute_command(
    command: str,
    shell: str,
    timeout: float,
    max_output_length: int,
    env_overrides: dict[str, str],
    cwd: str | None = None,
) -> CommandResult:
    """Execute a shell command and return the result."""
    merged_env = dict(os.environ)
    merged_env.update(env_overrides)

    start = time.monotonic()

    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        executable=shell,
        env=merged_env,
        cwd=cwd,
    )

    timed_out = False
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        timed_out = True
        proc.kill()
        await proc.wait()
        # Collect any partial output
        stdout_bytes = b""
        stderr_bytes = b""
        try:
            if proc.stdout:
                stdout_bytes = await asyncio.wait_for(proc.stdout.read(), timeout=1.0)
            if proc.stderr:
                stderr_bytes = await asyncio.wait_for(proc.stderr.read(), timeout=1.0)
        except (asyncio.TimeoutError, Exception):
            pass

    elapsed = time.monotonic() - start

    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")

    truncated, stdout, stderr = _truncate_output(stdout, stderr, max_output_length)

    if timed_out:
        status = "timeout"
        exit_code = None
    elif proc.returncode == 0:
        status = "success"
        exit_code = 0
    else:
        status = "error"
        exit_code = proc.returncode

    return CommandResult(
        status=status,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        execution_time=round(elapsed, 3),
        truncated=truncated,
        command=command,
    )


def _truncate_output(
    stdout: str, stderr: str, max_length: int
) -> tuple[bool, str, str]:
    """Truncate stdout and stderr to fit within max_length total.

    Prioritizes stdout. Returns (truncated, stdout, stderr).
    """
    total = len(stdout) + len(stderr)
    if total <= max_length:
        return (False, stdout, stderr)

    marker = "\n[...truncated]"
    marker_len = len(marker)

    # Allocate space: stdout first, then stderr
    stdout_budget = min(len(stdout), max_length)
    stderr_budget = max_length - stdout_budget

    # If stderr has more than its budget, we need to adjust
    if len(stderr) > stderr_budget and stderr_budget < max_length // 3:
        # Give stderr at least 1/3 of total if it needs it
        stderr_budget = min(len(stderr), max_length // 3)
        stdout_budget = max_length - stderr_budget

    truncated_stdout = stdout
    truncated_stderr = stderr

    if len(stdout) > stdout_budget:
        cut = max(stdout_budget - marker_len, 0)
        truncated_stdout = stdout[:cut] + marker

    if len(stderr) > stderr_budget:
        cut = max(stderr_budget - marker_len, 0)
        truncated_stderr = stderr[:cut] + marker

    return (True, truncated_stdout, truncated_stderr)
