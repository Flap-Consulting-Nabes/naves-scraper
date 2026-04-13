"""Tests for fire-and-forget task registry."""
import asyncio

from api.task_registry import _tasks, drain, fire_and_track


class TestFireAndTrack:
    def test_task_added_to_registry(self):
        async def _run():
            async def noop():
                pass

            task = fire_and_track(noop(), name="test")
            assert task in _tasks
            await task

        asyncio.run(_run())

    def test_task_removed_after_completion(self):
        async def _run():
            async def noop():
                pass

            task = fire_and_track(noop(), name="cleanup-test")
            await task
            # Give the done callback a tick to fire
            await asyncio.sleep(0)
            assert task not in _tasks

        asyncio.run(_run())

    def test_task_name_propagated(self):
        async def _run():
            async def noop():
                pass

            task = fire_and_track(noop(), name="my-named-task")
            assert task.get_name() == "my-named-task"
            await task

        asyncio.run(_run())


class TestDrain:
    def test_drain_with_no_tasks(self):
        asyncio.run(drain(timeout=0.5))

    def test_drain_waits_for_tasks(self):
        results = []

        async def _run():
            async def slow():
                await asyncio.sleep(0.1)
                results.append("done")

            fire_and_track(slow(), name="drain-test")
            await drain(timeout=5.0)

        asyncio.run(_run())
        assert "done" in results

    def test_drain_cancels_on_timeout(self):
        async def _run():
            async def forever():
                await asyncio.sleep(999)

            fire_and_track(forever(), name="timeout-test")
            await drain(timeout=0.1)
            # After drain, the stuck task should have been cancelled
            await asyncio.sleep(0)

        asyncio.run(_run())
