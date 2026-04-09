"""Tests for keepalive helpers."""

import asyncio

import pytest

from shell_mcp.keepalive import run_with_keepalive


class FakeContext:
    def __init__(self, fail_after: int | None = None) -> None:
        self.fail_after = fail_after
        self.messages: list[tuple[int, int, str]] = []

    async def report_progress(self, *, progress: int, total: int, message: str) -> None:
        self.messages.append((progress, total, message))
        if self.fail_after is not None and len(self.messages) >= self.fail_after:
            raise RuntimeError("disconnected")


@pytest.mark.asyncio
async def test_run_with_keepalive_reports_progress():
    ctx = FakeContext()

    async def slow() -> str:
        await asyncio.sleep(0.03)
        return "done"

    result = await run_with_keepalive(ctx, slow(), 0.01)

    assert result == "done"
    assert ctx.messages
    assert "Command still running" in ctx.messages[0][2]


@pytest.mark.asyncio
async def test_run_with_keepalive_ignores_progress_errors():
    ctx = FakeContext(fail_after=1)

    async def slow() -> str:
        await asyncio.sleep(0.03)
        return "done"

    result = await run_with_keepalive(ctx, slow(), 0.01)

    assert result == "done"
    assert len(ctx.messages) == 1
