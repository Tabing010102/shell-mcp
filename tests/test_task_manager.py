"""Tests for task_manager module."""

import asyncio
import os
import shlex

import pytest

from shell_mcp.config import ShellMCPConfig
from shell_mcp.task_manager import TaskManager


async def _wait_for_terminal_task(
    manager: TaskManager, task_id: str, attempts: int = 50
):
    for _ in range(attempts):
        task = await manager.get_task(task_id)
        if task is not None and task.status != "running":
            return task
        await asyncio.sleep(0.02)
    pytest.fail(f"Task {task_id} did not reach a terminal state in time")


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@pytest.fixture
async def manager():
    mgr = TaskManager(ShellMCPConfig())
    yield mgr
    await mgr.cleanup()


@pytest.mark.asyncio
async def test_start_and_query(manager):
    task_id = await manager.start_task("echo hello", "/bin/sh", 10)
    task = await manager.get_task(task_id)
    assert task is not None
    assert task.command == "echo hello"
    assert task.task_id == task_id


@pytest.mark.asyncio
async def test_completion(manager):
    task_id = await manager.start_task("echo done", "/bin/sh", 10)
    # Wait for fast command to complete
    await asyncio.sleep(0.5)
    task = await manager.get_task(task_id)
    assert task is not None
    assert task.status == "completed"
    assert task.result is not None
    assert task.result.stdout.strip() == "done"


@pytest.mark.asyncio
async def test_list_tasks(manager):
    await manager.start_task("echo a", "/bin/sh", 10)
    await manager.start_task("echo b", "/bin/sh", 10)
    tasks = await manager.list_tasks()
    assert len(tasks) == 2


@pytest.mark.asyncio
async def test_stop_task(manager):
    task_id = await manager.start_task("sleep 60", "/bin/sh", 300)
    await asyncio.sleep(0.1)
    stopped = await manager.stop_task(task_id)
    assert stopped is True
    await asyncio.sleep(0.3)
    task = await manager.get_task(task_id)
    assert task is not None
    assert task.status == "killed"


@pytest.mark.asyncio
async def test_stop_task_kills_process_group(manager, tmp_path):
    pid_file = tmp_path / "task.pid"
    python_code = (
        "import os, pathlib, time; "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid())); "
        "time.sleep(60)"
    )
    command = f"python3 -c {shlex.quote(python_code)}"

    task_id = await manager.start_task(command, "/bin/sh", 300)

    for _ in range(20):
        if pid_file.exists():
            break
        await asyncio.sleep(0.05)

    assert pid_file.exists()
    pid = int(pid_file.read_text())

    stopped = await manager.stop_task(task_id)
    assert stopped is True

    for _ in range(20):
        task = await manager.get_task(task_id)
        if task is not None and task.status == "killed":
            break
        await asyncio.sleep(0.05)

    task = await manager.get_task(task_id)
    assert task is not None
    assert task.status == "killed"

    for _ in range(20):
        if not _pid_exists(pid):
            break
        await asyncio.sleep(0.05)

    assert not _pid_exists(pid)


@pytest.mark.asyncio
async def test_stop_nonexistent(manager):
    stopped = await manager.stop_task("nonexistent")
    assert stopped is False


@pytest.mark.asyncio
async def test_get_nonexistent(manager):
    task = await manager.get_task("nonexistent")
    assert task is None


@pytest.mark.asyncio
async def test_task_id_uniqueness(manager):
    id1 = await manager.start_task("echo 1", "/bin/sh", 10)
    id2 = await manager.start_task("echo 2", "/bin/sh", 10)
    assert id1 != id2


@pytest.mark.asyncio
async def test_timeout_in_background(manager):
    config = ShellMCPConfig(default_timeout=0.5)
    mgr = TaskManager(config)
    task_id = await mgr.start_task("sleep 60", "/bin/sh", 0.5)
    await asyncio.sleep(1.5)
    task = await mgr.get_task(task_id)
    assert task is not None
    assert task.status == "timeout"
    await mgr.cleanup()


@pytest.mark.asyncio
async def test_background_start_failure_records_error_result(manager):
    task_id = await manager.start_task("echo hello", "/definitely/not/a/shell", 10)
    await asyncio.sleep(0.1)
    task = await manager.get_task(task_id)
    assert task is not None
    assert task.status == "error"
    assert task.result is not None
    assert "Failed to start command" in task.result.stderr


@pytest.mark.asyncio
async def test_background_task_output_truncation_mode_override():
    mgr = TaskManager(
        ShellMCPConfig(max_output_length=20, output_truncation_mode="head")
    )

    try:
        task_id = await mgr.start_task(
            (
                "python3 -c \"import sys; "
                "sys.stdout.write('ABCDEFGHIJKLMNOPQRSTUVWXYZ')\""
            ),
            "/bin/sh",
            10,
            output_truncation_mode="tail",
        )

        task = await _wait_for_terminal_task(mgr, task_id)

        assert task.result is not None
        assert task.result.truncated is True
        assert task.result.stdout == "[...truncated]UVWXYZ"
    finally:
        await mgr.cleanup()


@pytest.mark.asyncio
async def test_completed_tasks_expire_after_ttl():
    mgr = TaskManager(ShellMCPConfig(completed_task_ttl=0.25))

    task_id = await mgr.start_task("echo expire-me", "/bin/sh", 10)

    task = await _wait_for_terminal_task(mgr, task_id)
    assert task.status == "completed"

    await asyncio.sleep(0.35)

    assert await mgr.get_task(task_id) is None
    await mgr.cleanup()


@pytest.mark.asyncio
async def test_completed_task_ttl_zero_disables_expiry():
    mgr = TaskManager(ShellMCPConfig(completed_task_ttl=0))

    task_id = await mgr.start_task("echo keep-me", "/bin/sh", 10)
    await asyncio.sleep(0.2)
    await asyncio.sleep(0.2)

    task = await mgr.get_task(task_id)
    assert task is not None
    assert task.status == "completed"
    await mgr.cleanup()
