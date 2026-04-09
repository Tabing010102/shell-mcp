"""Background task management for shell commands."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import ShellMCPConfig

from .executor import CommandResult, execute_command


@dataclass
class BackgroundTask:
    """A background shell command task."""

    task_id: str
    command: str
    status: str  # "running", "completed", "error", "timeout", "killed"
    created_at: float
    completed_at: float | None = None
    result: CommandResult | None = None
    _asyncio_task: asyncio.Task | None = field(default=None, repr=False)


class TaskManager:
    """Manages background shell command tasks. All state is in-memory."""

    def __init__(self, config: ShellMCPConfig) -> None:
        self._tasks: dict[str, BackgroundTask] = {}
        self._config = config
        self._lock = asyncio.Lock()

    async def start_task(
        self,
        command: str,
        shell: str,
        timeout: float,
        cwd: str | None = None,
    ) -> str:
        """Launch a command in background, return task_id."""
        task_id = uuid.uuid4().hex[:12]
        bg_task = BackgroundTask(
            task_id=task_id,
            command=command,
            status="running",
            created_at=time.time(),
        )

        async def _run() -> None:
            try:
                result = await execute_command(
                    command=command,
                    shell=shell,
                    timeout=timeout,
                    max_output_length=self._config.max_output_length,
                    env_overrides=self._config.non_interactive_env,
                    cwd=cwd,
                )
                async with self._lock:
                    bg_task.result = result
                    bg_task.status = result.status
                    bg_task.completed_at = time.time()
            except asyncio.CancelledError:
                async with self._lock:
                    bg_task.status = "killed"
                    bg_task.completed_at = time.time()
                raise
            except Exception:
                async with self._lock:
                    bg_task.status = "error"
                    bg_task.completed_at = time.time()

        asyncio_task = asyncio.create_task(_run())
        bg_task._asyncio_task = asyncio_task

        async with self._lock:
            self._tasks[task_id] = bg_task

        return task_id

    async def get_task(self, task_id: str) -> BackgroundTask | None:
        """Return task info or None if not found."""
        async with self._lock:
            return self._tasks.get(task_id)

    async def list_tasks(self) -> list[BackgroundTask]:
        """Return all tasks."""
        async with self._lock:
            return list(self._tasks.values())

    async def stop_task(self, task_id: str) -> bool:
        """Cancel a running task. Return True if it was running and is now stopped."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.status != "running":
                return False
            if task._asyncio_task and not task._asyncio_task.done():
                task._asyncio_task.cancel()
                return True
            return False

    async def cleanup(self) -> None:
        """Cancel all running tasks. Used for shutdown."""
        async with self._lock:
            for task in self._tasks.values():
                if task._asyncio_task and not task._asyncio_task.done():
                    task._asyncio_task.cancel()
        # Wait briefly for cancellations to propagate
        for task in list(self._tasks.values()):
            if task._asyncio_task and not task._asyncio_task.done():
                try:
                    await asyncio.wait_for(task._asyncio_task, timeout=1.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass
