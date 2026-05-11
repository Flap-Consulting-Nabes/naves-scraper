"""Tests for scripts/migrate_url_to_source.py (back-fill old CMS items)."""
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.migrate_url_to_source import migrate_items


@pytest.mark.asyncio
async def test_moves_milanuncios_url_to_source():
    items = [{
        "id": "item-1",
        "fieldData": {
            "name": "Warehouse A",
            "google-place-id": "https://www.milanuncios.com/x/foo-111.htm",
            "source": "",
        },
        "isDraft": True,
        "isArchived": False,
    }]
    client = AsyncMock()
    client.list_items = AsyncMock(return_value=items)
    client.update_items = AsyncMock(return_value={"updated": 1, "errors": []})

    summary = await migrate_items(client, cms_locale_id=None, dry_run=False)

    assert summary == {
        "moved": 1,
        "skipped_empty": 0,
        "skipped_non_milanuncios": 0,
        "failed": 0,
    }
    client.update_items.assert_awaited_once()
    sent = client.update_items.await_args.args[0]
    assert sent == [{
        "id": "item-1",
        "fieldData": {
            "source": "https://www.milanuncios.com/x/foo-111.htm",
            "google-place-id": "",
        },
    }]


@pytest.mark.asyncio
async def test_skips_non_milanuncios_value():
    items = [{
        "id": "item-2",
        "fieldData": {
            "name": "Warehouse B",
            "google-place-id": "ChIJN1t_tDeuEmsRUsoyG83frY4",
            "source": "",
        },
    }]
    client = AsyncMock()
    client.list_items = AsyncMock(return_value=items)
    client.update_items = AsyncMock()

    summary = await migrate_items(client, cms_locale_id=None, dry_run=False)

    assert summary == {
        "moved": 0,
        "skipped_empty": 0,
        "skipped_non_milanuncios": 1,
        "failed": 0,
    }
    client.update_items.assert_not_called()


@pytest.mark.asyncio
async def test_skips_empty_field():
    items = [{
        "id": "item-3",
        "fieldData": {"name": "Warehouse C", "google-place-id": "", "source": ""},
    }]
    client = AsyncMock()
    client.list_items = AsyncMock(return_value=items)
    client.update_items = AsyncMock()

    summary = await migrate_items(client, cms_locale_id=None, dry_run=False)

    assert summary == {
        "moved": 0,
        "skipped_empty": 1,
        "skipped_non_milanuncios": 0,
        "failed": 0,
    }
    client.update_items.assert_not_called()


@pytest.mark.asyncio
async def test_dry_run_does_not_call_update():
    items = [{
        "id": "item-4",
        "fieldData": {"google-place-id": "https://www.milanuncios.com/x/foo-222.htm"},
    }]
    client = AsyncMock()
    client.list_items = AsyncMock(return_value=items)
    client.update_items = AsyncMock()

    summary = await migrate_items(client, cms_locale_id=None, dry_run=True)

    assert summary["moved"] == 1
    client.update_items.assert_not_called()
