"""Shell command execution with asyncio subprocess."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import subprocess
import time
from dataclasses import dataclass


@dataclass
class CommandResult:
    """Result of a shell command execution."""

    status: str  # "success", "error", "timeout"
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

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            executable=shell,
            env=merged_env,
            cwd=cwd,
            start_new_session=True,
        )
    except OSError as exc:
        return _build_result(
            command=command,
            status="error",
            exit_code=None,
            stdout="",
            stderr=f"Failed to start command: {type(exc).__name__}: {exc}",
            elapsed=time.monotonic() - start,
            max_output_length=max_output_length,
        )

    timed_out = False
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        timed_out = True
        stdout_bytes, stderr_bytes = await _terminate_process(proc)
    except asyncio.CancelledError:
        with contextlib.suppress(Exception):
            await asyncio.shield(_terminate_process(proc))
        raise
    except Exception as exc:
        stdout_bytes, stderr_bytes = await _terminate_process(proc)
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        if stderr:
            stderr = f"{stderr}\nCommand execution failed: {type(exc).__name__}: {exc}"
        else:
            stderr = f"Command execution failed: {type(exc).__name__}: {exc}"
        return _build_result(
            command=command,
            status="error",
            exit_code=None,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr,
            elapsed=time.monotonic() - start,
            max_output_length=max_output_length,
        )

    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")

    if timed_out:
        status = "timeout"
        exit_code = None
    elif proc.returncode == 0:
        status = "success"
        exit_code = 0
    else:
        status = "error"
        exit_code = proc.returncode

    return _build_result(
        command=command,
        status=status,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        elapsed=time.monotonic() - start,
        max_output_length=max_output_length,
    )


def _build_result(
    command: str,
    status: str,
    exit_code: int | None,
    stdout: str,
    stderr: str,
    elapsed: float,
    max_output_length: int,
) -> CommandResult:
    """Build a CommandResult with consistent truncation/rounding."""
    truncated, stdout, stderr = _truncate_output(stdout, stderr, max_output_length)
    return CommandResult(
        status=status,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        execution_time=round(elapsed, 3),
        truncated=truncated,
        command=command,
    )


async def _terminate_process(
    proc: asyncio.subprocess.Process,
) -> tuple[bytes, bytes]:
    """Terminate a process group and collect any remaining output."""
    if proc.returncode is None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            with contextlib.suppress(ProcessLookupError):
                proc.kill()

    try:
        return await asyncio.wait_for(proc.communicate(), timeout=1.0)
    except Exception:
        stdout_bytes = b""
        stderr_bytes = b""
        try:
            if proc.stdout is not None:
                stdout_bytes = await asyncio.wait_for(proc.stdout.read(), timeout=0.5)
        except Exception:
            pass
        try:
            if proc.stderr is not None:
                stderr_bytes = await asyncio.wait_for(proc.stderr.read(), timeout=0.5)
        except Exception:
            pass
        with contextlib.suppress(Exception):
            await proc.wait()
        return (stdout_bytes, stderr_bytes)


def _truncate_output(
    stdout: str, stderr: str, max_length: int
) -> tuple[bool, str, str]:
    """Truncate stdout and stderr to fit within max_length total.

    Prioritizes stdout. Returns (truncated, stdout, stderr).
    """
    total = len(stdout) + len(stderr)
    if total <= max_length:
        return (False, stdout, stderr)

    if max_length <= 0:
        return (True, "", "")

    stdout_budget = min(len(stdout), max_length)
    stderr_budget = max_length - stdout_budget

    if stderr and stderr_budget == 0:
        stderr_budget = min(len(stderr), max_length // 3)
        stdout_budget = max_length - stderr_budget
    elif len(stderr) > stderr_budget and stderr_budget < max_length // 3:
        stderr_budget = min(len(stderr), max_length // 3)
        stdout_budget = max_length - stderr_budget

    truncated_stdout, stdout_truncated = _fit_output_to_budget(stdout, stdout_budget)
    truncated_stderr, stderr_truncated = _fit_output_to_budget(stderr, stderr_budget)

    return (
        stdout_truncated or stderr_truncated,
        truncated_stdout,
        truncated_stderr,
    )


def _fit_output_to_budget(text: str, budget: int) -> tuple[str, bool]:
    """Fit one output stream into the allotted final-size budget."""
    if budget <= 0:
        return ("", bool(text))
    if len(text) <= budget:
        return (text, False)

    marker = "[...truncated]"
    if budget <= len(marker):
        return (marker[:budget], True)

    keep = budget - len(marker)
    return (text[:keep] + marker, True)
