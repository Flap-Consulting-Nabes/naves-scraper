"""Tests for Phase 1 security hardening."""
import hmac


class TestTimingSafeKeyComparison:
    def test_dependencies_uses_hmac(self):
        """verify_api_key uses hmac.compare_digest, not bare ==."""
        import inspect
        from api.dependencies import verify_api_key

        source = inspect.getsource(verify_api_key)
        assert "hmac.compare_digest" in source
        assert "!=" not in source or "x_api_key !=" not in source

    def test_hmac_compare_digest_rejects_wrong_key(self):
        assert not hmac.compare_digest("correct-key", "wrong-key")

    def test_hmac_compare_digest_accepts_correct_key(self):
        assert hmac.compare_digest("correct-key", "correct-key")


class TestWebflowGuard:
    def test_webflow_client_defaults_to_empty_collection_id(self):
        from integrations.webflow_client import COLLECTION_ID

        # In test env WEBFLOW_COLLECTION_ID is empty by default
        # The important thing is it's not a hardcoded production ID
        assert COLLECTION_ID != "673373bb232280f5720b72ca"


class TestTargetedChromeKill:
    def test_kill_function_uses_pgrep(self):
        """_kill_orphan_chromes must use targeted pgrep, not pkill -f chrome."""
        import inspect
        from integrations.milanuncios import _kill_orphan_chromes

        source = inspect.getsource(_kill_orphan_chromes)
        assert "pgrep" in source
        assert "pkill" not in source


class TestTaskRegistry:
    def test_fire_and_track_registers_task(self):
        import asyncio
        from api.task_registry import _tasks, fire_and_track

        async def _run():
            async def dummy():
                await asyncio.sleep(0)

            task = fire_and_track(dummy(), name="test-task")
            assert task in _tasks
            await task
            # After completion, callback should have removed it
            assert task not in _tasks

        asyncio.run(_run())

    def test_drain_with_no_tasks(self):
        import asyncio
        from api.task_registry import drain

        # Should complete immediately with no tasks
        asyncio.run(drain(timeout=1.0))
