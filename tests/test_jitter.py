"""Tests for jitter — must be async, not blocking."""
import asyncio
import inspect
import time

from utils.jitter import random_delay


class TestJitterIsAsync:
    def test_random_delay_is_coroutine_function(self):
        assert inspect.iscoroutinefunction(random_delay)

    def test_does_not_use_time_sleep(self):
        source = inspect.getsource(random_delay)
        assert "time.sleep" not in source
        assert "asyncio.sleep" in source

    def test_random_delay_completes_quickly(self):
        """With small bounds, should complete without blocking the event loop."""
        start = time.monotonic()
        asyncio.run(random_delay(0.01, 0.05))
        elapsed = time.monotonic() - start
        assert elapsed < 1.0  # generous upper bound

    def test_random_delay_respects_bounds(self):
        async def _measure():
            start = time.monotonic()
            await random_delay(0.1, 0.2)
            return time.monotonic() - start

        elapsed = asyncio.run(_measure())
        assert 0.08 <= elapsed <= 0.5  # tolerance for scheduling jitter
