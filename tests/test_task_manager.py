"""Tests for task_manager module."""

import asyncio

import pytest

from shell_mcp.config import ShellMCPConfig
from shell_mcp.task_manager import TaskManager


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
    assert task.status in ("completed", "success")
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
