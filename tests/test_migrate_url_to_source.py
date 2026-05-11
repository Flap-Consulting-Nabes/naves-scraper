"""Tests for scripts/migrate_url_to_source.py (back-fill old CMS items)."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.migrate_url_to_source import _parse_iso, migrate_items


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
        "skipped_too_old": 0,
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
        "skipped_too_old": 0,
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
        "skipped_too_old": 0,
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


def test_parse_iso_handles_webflow_format():
    # Webflow returns trailing-Z timestamps like 2026-05-11T10:42:26.906Z
    parsed = _parse_iso("2026-05-11T10:42:26.906Z")
    assert parsed is not None
    assert parsed.tzinfo is not None
    assert parsed.year == 2026 and parsed.month == 5 and parsed.day == 11


def test_parse_iso_returns_none_on_garbage():
    assert _parse_iso(None) is None
    assert _parse_iso("") is None
    assert _parse_iso("not-a-date") is None


@pytest.mark.asyncio
async def test_since_filter_skips_older_items():
    # Two items: one updated yesterday, one updated 30 days ago.
    # With --since-days 7, only yesterday's item should move.
    now = datetime.now(timezone.utc)
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    long_ago = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    items = [
        {
            "id": "recent",
            "fieldData": {"google-place-id": "https://www.milanuncios.com/x/foo-111.htm"},
            "lastUpdated": yesterday,
        },
        {
            "id": "old",
            "fieldData": {"google-place-id": "https://www.milanuncios.com/x/bar-222.htm"},
            "lastUpdated": long_ago,
        },
    ]
    client = AsyncMock()
    client.list_items = AsyncMock(return_value=items)
    client.update_items = AsyncMock(return_value={"updated": 1, "errors": []})

    since = now - timedelta(days=7)
    summary = await migrate_items(client, cms_locale_id=None, dry_run=False, since=since)

    assert summary["moved"] == 1
    assert summary["skipped_too_old"] == 1
    sent = client.update_items.await_args.args[0]
    assert len(sent) == 1
    assert sent[0]["id"] == "recent"


@pytest.mark.asyncio
async def test_since_filter_treats_missing_timestamp_as_too_old():
    # Defensive: an item with no lastUpdated/createdOn must not silently
    # bypass the date filter.
    now = datetime.now(timezone.utc)
    items = [{
        "id": "no-timestamp",
        "fieldData": {"google-place-id": "https://www.milanuncios.com/x/foo-111.htm"},
    }]
    client = AsyncMock()
    client.list_items = AsyncMock(return_value=items)
    client.update_items = AsyncMock()

    since = now - timedelta(days=7)
    summary = await migrate_items(client, cms_locale_id=None, dry_run=False, since=since)

    assert summary["moved"] == 0
    assert summary["skipped_too_old"] == 1
    client.update_items.assert_not_called()


@pytest.mark.asyncio
async def test_since_filter_falls_back_to_createdOn():
    # When lastUpdated is missing, createdOn should be used.
    now = datetime.now(timezone.utc)
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    items = [{
        "id": "uses-createdOn",
        "fieldData": {"google-place-id": "https://www.milanuncios.com/x/foo-111.htm"},
        "createdOn": yesterday,
    }]
    client = AsyncMock()
    client.list_items = AsyncMock(return_value=items)
    client.update_items = AsyncMock(return_value={"updated": 1, "errors": []})

    since = now - timedelta(days=7)
    summary = await migrate_items(client, cms_locale_id=None, dry_run=False, since=since)

    assert summary["moved"] == 1
    assert summary["skipped_too_old"] == 0
