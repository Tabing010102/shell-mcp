"""MCP server definition and tool registrations."""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .command_parser import validate_command
from .config import ShellMCPConfig, resolve_shell
from .executor import execute_command
from .keepalive import run_with_keepalive
from .task_manager import TaskManager

# Module-level globals, initialized by cli.py before mcp.run()
config: ShellMCPConfig = ShellMCPConfig()
task_manager: TaskManager = TaskManager(config)

mcp = FastMCP("shell-mcp", json_response=True)


def _default_transport_security_for_host(
    host: str,
) -> TransportSecuritySettings | None:
    """Mirror FastMCP's default transport security selection for a host."""
    if host in ("127.0.0.1", "localhost", "::1"):
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"],
            allowed_origins=[
                "http://127.0.0.1:*",
                "http://localhost:*",
                "http://[::1]:*",
            ],
        )
    return None


def configure_mcp_runtime(cfg: ShellMCPConfig) -> None:
    """Apply runtime HTTP settings to the FastMCP instance."""
    mcp.settings.host = cfg.host
    mcp.settings.port = cfg.port
    mcp.settings.transport_security = _default_transport_security_for_host(
        cfg.host
    )


def _result_to_dict(obj: Any) -> dict:
    """Convert a dataclass to a JSON-serializable dict."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        d = {}
        for f in dataclasses.fields(obj):
            if f.name.startswith("_"):
                continue
            val = getattr(obj, f.name)
            if dataclasses.is_dataclass(val) and not isinstance(val, type):
                d[f.name] = _result_to_dict(val)
            else:
                d[f.name] = val
        return d
    return obj


@mcp.tool()
async def execute_shell_command(
    command: str,
    background: bool = False,
    timeout: float | None = None,
    shell: str = "",
    cwd: str | None = None,
    ctx: Context = None,
) -> str:
    """Execute a shell command.

    Args:
        command: The shell command to execute.
        background: If True, run in background and return task_id immediately.
        timeout: Timeout in seconds. If None, uses server default.
        shell: Shell to use (e.g. /bin/bash). Empty means auto-detect.
        cwd: Working directory. None means current directory.

    Returns:
        JSON string with execution result or background task info.
    """
    # Validate against blacklist/whitelist
    allowed, reason = validate_command(command, config.blacklist, config.whitelist)
    if not allowed:
        return json.dumps({"status": "rejected", "reason": reason})

    resolved_shell = resolve_shell(shell or config.shell)
    resolved_timeout = timeout if timeout is not None else config.default_timeout

    if background:
        task_id = await task_manager.start_task(
            command=command,
            shell=resolved_shell,
            timeout=resolved_timeout,
            cwd=cwd,
        )
        return json.dumps({
            "task_id": task_id,
            "status": "running",
            "message": "Command started in background",
        })

    # Foreground execution with keepalive
    coro = execute_command(
        command=command,
        shell=resolved_shell,
        timeout=resolved_timeout,
        max_output_length=config.max_output_length,
        env_overrides=config.non_interactive_env,
        cwd=cwd,
    )

    if ctx is not None:
        result = await run_with_keepalive(ctx, coro, config.keepalive_interval)
    else:
        result = await coro

    return json.dumps(_result_to_dict(result))


@mcp.tool()
async def get_task_status(task_id: str) -> str:
    """Get status of a background task.

    Args:
        task_id: The task ID returned by execute_shell_command.

    Returns:
        JSON string with task status and result if completed.
    """
    task = await task_manager.get_task(task_id)
    if task is None:
        return json.dumps({"error": f"Task '{task_id}' not found"})

    info: dict[str, Any] = {
        "task_id": task.task_id,
        "command": task.command,
        "status": task.status,
        "created_at": task.created_at,
        "completed_at": task.completed_at,
    }
    if task.result is not None:
        info["result"] = _result_to_dict(task.result)

    return json.dumps(info)


@mcp.tool()
async def stop_background_task(task_id: str) -> str:
    """Stop a running background task.

    Args:
        task_id: The task ID to stop.

    Returns:
        JSON string indicating success or failure.
    """
    stopped = await task_manager.stop_task(task_id)
    if stopped:
        return json.dumps({"status": "stopped", "task_id": task_id})
    return json.dumps({"status": "not_stopped", "reason": "Task not found or not running"})


@mcp.tool()
async def list_background_tasks() -> str:
    """List all background tasks.

    Returns:
        JSON array of task summaries.
    """
    tasks = await task_manager.list_tasks()
    summaries = [
        {
            "task_id": t.task_id,
            "command": t.command,
            "status": t.status,
            "created_at": t.created_at,
            "completed_at": t.completed_at,
        }
        for t in tasks
    ]
    return json.dumps(summaries)
