"""Background task management for shell commands."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field

from .config import OutputTruncationMode, ShellMCPConfig, normalize_output_truncation_mode

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
        self._reaper_task: asyncio.Task[None] | None = None

    async def start_task(
        self,
        command: str,
        shell: str,
        timeout: float,
        cwd: str | None = None,
        output_truncation_mode: OutputTruncationMode | None = None,
    ) -> str:
        """Launch a command in background, return task_id."""
        await self._prune_expired_tasks()
        await self._ensure_reaper_started()

        resolved_output_truncation_mode = normalize_output_truncation_mode(
            output_truncation_mode or self._config.output_truncation_mode
        )

        task_id = uuid.uuid4().hex[:12]
        bg_task = BackgroundTask(
            task_id=task_id,
            command=command,
            status="running",
            created_at=time.time(),
        )

        async def _run() -> None:
            started = time.monotonic()
            try:
                result = await execute_command(
                    command=command,
                    shell=shell,
                    timeout=timeout,
                    max_output_length=self._config.max_output_length,
                    env_overrides=self._config.non_interactive_env,
                    cwd=cwd,
                    output_truncation_mode=resolved_output_truncation_mode,
                )
                async with self._lock:
                    bg_task.result = result
                    bg_task.status = _task_status_from_result(result)
                    bg_task.completed_at = time.time()
            except asyncio.CancelledError:
                async with self._lock:
                    bg_task.status = "killed"
                    bg_task.completed_at = time.time()
                raise
            except Exception as exc:
                async with self._lock:
                    bg_task.result = CommandResult(
                        status="error",
                        exit_code=None,
                        stdout="",
                        stderr=(
                            f"Background task failed: {type(exc).__name__}: {exc}"
                        ),
                        execution_time=round(time.monotonic() - started, 3),
                        truncated=False,
                        command=command,
                    )
                    bg_task.status = "error"
                    bg_task.completed_at = time.time()
            finally:
                async with self._lock:
                    if bg_task._asyncio_task is asyncio.current_task():
                        bg_task._asyncio_task = None

        asyncio_task = asyncio.create_task(_run())
        bg_task._asyncio_task = asyncio_task

        async with self._lock:
            self._tasks[task_id] = bg_task

        return task_id

    async def get_task(self, task_id: str) -> BackgroundTask | None:
        """Return task info or None if not found."""
        await self._prune_expired_tasks()
        async with self._lock:
            return self._tasks.get(task_id)

    async def list_tasks(self) -> list[BackgroundTask]:
        """Return all tasks."""
        await self._prune_expired_tasks()
        async with self._lock:
            return list(self._tasks.values())

    async def stop_task(self, task_id: str) -> bool:
        """Cancel a running task. Return True if it was running and is now stopped."""
        await self._prune_expired_tasks()
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
            running_tasks = [
                task._asyncio_task
                for task in self._tasks.values()
                if task._asyncio_task and not task._asyncio_task.done()
            ]
            reaper_task = (
                self._reaper_task
                if self._reaper_task and not self._reaper_task.done()
                else None
            )

            for task in running_tasks:
                task.cancel()
            if reaper_task is not None:
                reaper_task.cancel()

        # Wait briefly for cancellations to propagate
        for task in running_tasks:
            try:
                await asyncio.wait_for(task, timeout=1.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

        if reaper_task is not None:
            try:
                await asyncio.wait_for(reaper_task, timeout=1.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

        async with self._lock:
            self._tasks.clear()
            self._reaper_task = None

    async def _ensure_reaper_started(self) -> None:
        """Start the completed-task reaper loop if retention is enabled."""
        if self._config.completed_task_ttl <= 0:
            return

        async with self._lock:
            if self._reaper_task is None or self._reaper_task.done():
                self._reaper_task = asyncio.create_task(
                    self._expire_completed_tasks_loop()
                )

    async def _prune_expired_tasks(self) -> None:
        """Remove expired completed task records from memory."""
        ttl = self._config.completed_task_ttl
        if ttl <= 0:
            return

        now = time.time()
        async with self._lock:
            expired_task_ids = [
                task_id
                for task_id, task in self._tasks.items()
                if _task_has_expired(task, now, ttl)
            ]
            for task_id in expired_task_ids:
                self._tasks.pop(task_id, None)

    async def _expire_completed_tasks_loop(self) -> None:
        """Periodically reap completed task records after their TTL elapses."""
        try:
            while True:
                await asyncio.sleep(_completed_task_reap_interval(
                    self._config.completed_task_ttl
                ))
                await self._prune_expired_tasks()
        except asyncio.CancelledError:
            raise
        finally:
            current_task = asyncio.current_task()
            async with self._lock:
                if self._reaper_task is current_task:
                    self._reaper_task = None


def _task_status_from_result(result: CommandResult) -> str:
    """Map a command result to the public background task status."""
    if result.status == "success":
        return "completed"
    return result.status


def _task_has_expired(task: BackgroundTask, now: float, ttl: float) -> bool:
    """Check whether a completed task record has exceeded its retention TTL."""
    if task.status == "running" or task.completed_at is None:
        return False
    return now - task.completed_at >= ttl


def _completed_task_reap_interval(ttl: float) -> float:
    """Pick a reasonable cleanup interval for expired task records."""
    return max(0.05, min(ttl / 2, 60.0))
