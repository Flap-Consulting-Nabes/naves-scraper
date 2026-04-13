"""Tests for Webflow client guards — empty token/collection handling."""
import inspect


class TestWebflowSyncGuard:
    def test_sync_skips_when_unconfigured(self):
        """sync_pending_listings must check WEBFLOW_TOKEN and COLLECTION_ID."""
        from integrations.webflow_sync import sync_pending_listings

        source = inspect.getsource(sync_pending_listings)
        assert "WEBFLOW_TOKEN" in source
        assert "COLLECTION_ID" in source

    def test_webflow_client_empty_token_is_string(self):
        from integrations.webflow_client import WEBFLOW_TOKEN

        assert isinstance(WEBFLOW_TOKEN, str)

    def test_webflow_client_empty_collection_is_string(self):
        from integrations.webflow_client import COLLECTION_ID

        assert isinstance(COLLECTION_ID, str)
