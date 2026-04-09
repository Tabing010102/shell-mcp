"""Tests for executor module."""

import pytest

from shell_mcp.executor import execute_command


@pytest.mark.asyncio
async def test_simple_success():
    result = await execute_command("echo hello", "/bin/sh", 10, 50000, {})
    assert result.status == "success"
    assert result.exit_code == 0
    assert result.stdout.strip() == "hello"
    assert result.truncated is False


@pytest.mark.asyncio
async def test_nonzero_exit():
    result = await execute_command("exit 1", "/bin/sh", 10, 50000, {})
    assert result.status == "error"
    assert result.exit_code == 1


@pytest.mark.asyncio
async def test_stderr_capture():
    result = await execute_command("echo err >&2", "/bin/sh", 10, 50000, {})
    assert result.stderr.strip() == "err"


@pytest.mark.asyncio
async def test_timeout():
    result = await execute_command("sleep 60", "/bin/sh", 0.5, 50000, {})
    assert result.status == "timeout"
    assert result.exit_code is None


@pytest.mark.asyncio
async def test_output_truncation():
    # Generate 1000 chars of output, limit to 100
    cmd = "python3 -c \"print('x' * 1000)\""
    result = await execute_command(cmd, "/bin/sh", 10, 100, {})
    assert result.truncated is True
    assert len(result.stdout) + len(result.stderr) <= 150  # some tolerance for marker


@pytest.mark.asyncio
async def test_stdin_devnull():
    """cat with no args reads stdin; with DEVNULL it gets EOF immediately."""
    result = await execute_command("cat", "/bin/sh", 2, 50000, {})
    assert result.status == "success"
    assert result.stdout == ""


@pytest.mark.asyncio
async def test_execution_time_recorded():
    result = await execute_command("echo fast", "/bin/sh", 10, 50000, {})
    assert result.execution_time >= 0


@pytest.mark.asyncio
async def test_environment_override():
    result = await execute_command(
        "echo $MY_TEST_VAR", "/bin/sh", 10, 50000, {"MY_TEST_VAR": "hello_test"}
    )
    assert result.stdout.strip() == "hello_test"


@pytest.mark.asyncio
async def test_working_directory():
    result = await execute_command("pwd", "/bin/sh", 10, 50000, {}, cwd="/tmp")
    # /tmp may resolve to /private/tmp on macOS
    assert "tmp" in result.stdout.strip()


@pytest.mark.asyncio
async def test_command_field():
    result = await execute_command("echo hi", "/bin/sh", 10, 50000, {})
    assert result.command == "echo hi"
