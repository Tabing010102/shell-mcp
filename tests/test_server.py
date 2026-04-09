"""Tests for the MCP server tools."""

import json

import pytest

from shell_mcp import server
from shell_mcp.config import ShellMCPConfig
from shell_mcp.task_manager import TaskManager


@pytest.fixture(autouse=True)
async def reset_server_globals():
    """Reset server globals before each test and cleanup after."""
    cfg = ShellMCPConfig(blacklist=["rm", "mkfs"])
    server.config = cfg
    server.task_manager = TaskManager(cfg)
    yield
    await server.task_manager.cleanup()


@pytest.mark.asyncio
async def test_execute_foreground():
    result_json = await server.execute_shell_command(command="echo test")
    result = json.loads(result_json)
    assert result["status"] == "success"
    assert result["exit_code"] == 0
    assert "test" in result["stdout"]


@pytest.mark.asyncio
async def test_execute_background():
    result_json = await server.execute_shell_command(
        command="echo bg", background=True
    )
    result = json.loads(result_json)
    assert "task_id" in result
    assert result["status"] == "running"


@pytest.mark.asyncio
async def test_background_lifecycle():
    import asyncio

    result_json = await server.execute_shell_command(
        command="echo lifecycle", background=True
    )
    result = json.loads(result_json)
    task_id = result["task_id"]

    await asyncio.sleep(0.5)

    status_json = await server.get_task_status(task_id=task_id)
    status = json.loads(status_json)
    assert status["status"] == "completed"
    assert status["result"]["stdout"].strip() == "lifecycle"
    assert status["result"]["status"] == "success"


@pytest.mark.asyncio
async def test_blacklist_rejection():
    result_json = await server.execute_shell_command(command="rm -rf /tmp/foo")
    result = json.loads(result_json)
    assert result["status"] == "rejected"
    assert "blacklisted" in result["reason"]


@pytest.mark.asyncio
async def test_blacklist_piped_rejection():
    result_json = await server.execute_shell_command(command="ls | rm foo")
    result = json.loads(result_json)
    assert result["status"] == "rejected"


@pytest.mark.asyncio
async def test_list_tasks():
    await server.execute_shell_command(command="echo task1", background=True)
    result_json = await server.list_background_tasks()
    result = json.loads(result_json)
    assert len(result) >= 1


@pytest.mark.asyncio
async def test_stop_background_task():
    import asyncio

    result_json = await server.execute_shell_command(
        command="sleep 60", background=True
    )
    result = json.loads(result_json)
    task_id = result["task_id"]

    await asyncio.sleep(0.2)

    stop_json = await server.stop_background_task(task_id=task_id)
    stop = json.loads(stop_json)
    assert stop["status"] == "stopped"


@pytest.mark.asyncio
async def test_get_nonexistent_task():
    result_json = await server.get_task_status(task_id="nonexistent123")
    result = json.loads(result_json)
    assert "error" in result


@pytest.mark.asyncio
async def test_whitelist_mode():
    cfg = ShellMCPConfig(whitelist=["echo", "ls"])
    server.config = cfg
    server.task_manager = TaskManager(cfg)

    # Allowed
    r = json.loads(await server.execute_shell_command(command="echo hi"))
    assert r["status"] == "success"

    # Blocked
    r = json.loads(await server.execute_shell_command(command="cat /etc/passwd"))
    assert r["status"] == "rejected"


@pytest.mark.asyncio
async def test_invalid_shell_returns_structured_error():
    result_json = await server.execute_shell_command(
        command="echo test", shell="/definitely/not/a/shell"
    )
    result = json.loads(result_json)
    assert result["status"] == "error"
    assert result["exit_code"] is None
    assert "Failed to start command" in result["stderr"]
