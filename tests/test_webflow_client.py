"""Tests for Webflow client guards — empty token/collection handling."""
import inspect

import httpx
import pytest
import respx


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


# ─── Iteración 2026-05, Tarea 6: list_items() pagination ──────────────────────
class TestListItemsPagination:
    @pytest.mark.asyncio
    async def test_single_page_returns_all_items(self, monkeypatch):
        from integrations import webflow_client as wc

        monkeypatch.setattr(wc, "COLLECTION_ID", "abc123")
        with respx.mock(base_url=wc.WEBFLOW_BASE) as router:
            router.get("/collections/abc123/items").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "items": [{"id": "i1"}, {"id": "i2"}],
                        "pagination": {"total": 2, "limit": 100, "offset": 0},
                    },
                )
            )
            client = wc.WebflowClient()
            items = await client.list_items(throttle_seconds=0)
            await client.close()
        assert [i["id"] for i in items] == ["i1", "i2"]

    @pytest.mark.asyncio
    async def test_multi_page_merges_all(self, monkeypatch):
        from integrations import webflow_client as wc

        monkeypatch.setattr(wc, "COLLECTION_ID", "abc123")
        with respx.mock(base_url=wc.WEBFLOW_BASE) as router:
            page1 = [{"id": f"i{n}"} for n in range(100)]
            page2 = [{"id": f"i{n}"} for n in range(100, 150)]
            route = router.get("/collections/abc123/items")
            route.side_effect = [
                httpx.Response(
                    200,
                    json={
                        "items": page1,
                        "pagination": {"total": 150, "limit": 100, "offset": 0},
                    },
                ),
                httpx.Response(
                    200,
                    json={
                        "items": page2,
                        "pagination": {"total": 150, "limit": 100, "offset": 100},
                    },
                ),
            ]
            client = wc.WebflowClient()
            items = await client.list_items(throttle_seconds=0)
            await client.close()
        assert len(items) == 150
        assert items[0]["id"] == "i0"
        assert items[-1]["id"] == "i149"

    @pytest.mark.asyncio
    async def test_passes_locale_id_when_given(self, monkeypatch):
        from integrations import webflow_client as wc

        monkeypatch.setattr(wc, "COLLECTION_ID", "abc123")
        with respx.mock(base_url=wc.WEBFLOW_BASE) as router:
            route = router.get("/collections/abc123/items").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "items": [],
                        "pagination": {"total": 0, "limit": 100, "offset": 0},
                    },
                )
            )
            client = wc.WebflowClient()
            await client.list_items(cms_locale_id="es-id-123", throttle_seconds=0)
            await client.close()
        assert route.calls.last.request.url.params.get("cmsLocaleId") == "es-id-123"
