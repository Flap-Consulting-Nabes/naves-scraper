"""
Registry for fire-and-forget asyncio tasks.

Prevents tasks from being garbage-collected (and silently lost) when
created with bare ``asyncio.create_task()``.  On shutdown the lifespan
handler calls ``drain()`` to wait for in-flight work to finish.
"""
import asyncio
import logging

logger = logging.getLogger(__name__)

_tasks: set[asyncio.Task] = set()


def fire_and_track(coro, *, name: str | None = None) -> asyncio.Task:
    """Create an asyncio task and keep a strong reference until it finishes."""
    task = asyncio.create_task(coro, name=name)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


async def drain(timeout: float = 30.0) -> None:
    """Wait for all tracked tasks to finish (called during shutdown)."""
    if not _tasks:
        return
    logger.info("[TaskRegistry] Draining %d in-flight tasks (timeout=%ss)...", len(_tasks), timeout)
    done, pending = await asyncio.wait(_tasks, timeout=timeout)
    if pending:
        logger.warning("[TaskRegistry] %d tasks still running after timeout — cancelling", len(pending))
        for t in pending:
            t.cancel()
