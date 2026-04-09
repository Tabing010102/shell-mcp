"""Keepalive logic for long-running foreground commands over streamable-http."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any, Coroutine, TypeVar

from mcp.server.fastmcp import Context

T = TypeVar("T")


async def run_with_keepalive(
    ctx: Context, coro: Coroutine[Any, Any, T], interval: float
) -> T:
    """Run a coroutine while sending periodic progress keepalive messages."""
    keepalive_task = asyncio.create_task(_keepalive_loop(ctx, interval))
    try:
        return await coro
    finally:
        keepalive_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await keepalive_task


async def _keepalive_loop(ctx: Context, interval: float) -> None:
    """Send periodic progress updates to keep the connection alive."""
    elapsed = 0.0
    while True:
        await asyncio.sleep(interval)
        elapsed += interval
        try:
            await ctx.report_progress(
                progress=0,
                total=0,
                message=f"Command still running ({elapsed:.0f}s elapsed)...",
            )
        except Exception:
            # If we can't send progress (e.g., disconnected), stop trying
            return
