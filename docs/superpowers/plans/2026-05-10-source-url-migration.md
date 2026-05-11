# Source URL Migration & Listing-ID Dedup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make new scrapes write the MilAnuncios listing URL into the new Webflow `source` field, dedup against existing CMS items by listing_id extracted via regex, and back-fill existing items that have the URL parked in `google-place-id`.

**Architecture:** Surgical edits to `integrations/webflow_sync.py` (one new helper, one renamed index function, two-line field-map change), one new one-shot script `scripts/migrate_url_to_source.py`, and 5 pytest cases. No schema migrations, no scraper-side changes, no new dependencies.

**Tech Stack:** Python 3.12, pytest, httpx (via existing `WebflowClient`), SQLite (via existing `get_unsynced_listings`).

**Spec:** `docs/superpowers/specs/2026-05-10-source-url-migration-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `integrations/webflow_sync.py` | Modify | Field-map precedence; new `_extract_listing_id`; rename + rewrite `_build_source_url_index` → `_build_listing_id_index`; per-row dedup check uses listing_id |
| `scripts/migrate_url_to_source.py` | Create | One-shot CLI: walk CMS items, move milanuncios URLs from `google-place-id` to `source`, clear old field |
| `tests/test_webflow_sync.py` | Modify | Add 4 tests (regex, field-map, dedup index, sync E2E); update `TestSourceUrlTempStashOnGooglePlaceId` for new precedence |
| `tests/test_migrate_url_to_source.py` | Create | 1 parametrized test (moves matching, skips non-matching) |
| `docs/decisions/2026-05-04-source-url-temp-stash.md` | Modify | Append "Resolved" footer with back-fill commit link (final task) |

---

## Task 1: Add `_extract_listing_id` helper (TDD)

**Files:**
- Modify: `integrations/webflow_sync.py` (add helper near top, after imports)
- Modify: `tests/test_webflow_sync.py` (add new test class)

- [ ] **Step 1.1: Write the failing test**

Add to `tests/test_webflow_sync.py` (top, after existing imports):

```python
from integrations.webflow_sync import _extract_listing_id


class TestExtractListingId:
    """Regex extraction of MilAnuncios listing ID from URL."""

    def test_typical_url(self):
        url = "https://www.milanuncios.com/venta-de-naves-industriales-en-atarfe-granada/atarfe-591093579.htm"
        assert _extract_listing_id(url) == "591093579"

    def test_alquiler_url(self):
        url = "https://www.milanuncios.com/alquiler-de-naves-industriales-en-montornes-del-valles-barcelona/montornes-del-valles-583152242.htm"
        assert _extract_listing_id(url) == "583152242"

    def test_missing_id_returns_none(self):
        assert _extract_listing_id("https://www.milanuncios.com/naves/foo.htm") is None

    def test_empty_string_returns_none(self):
        assert _extract_listing_id("") is None

    def test_none_returns_none(self):
        assert _extract_listing_id(None) is None

    def test_non_milanuncios_url_with_id_still_matches(self):
        # The regex is URL-shape-agnostic. We rely on the http(s)-shape
        # guard upstream in _build_listing_id_index to reject foreign hosts.
        assert _extract_listing_id("https://example.com/x-12345.htm") == "12345"
```

- [ ] **Step 1.2: Run the test to verify it fails**

```bash
python3 -m pytest tests/test_webflow_sync.py::TestExtractListingId -v
```

Expected: `ImportError` or `AttributeError: module 'integrations.webflow_sync' has no attribute '_extract_listing_id'`.

- [ ] **Step 1.3: Implement `_extract_listing_id`**

In `integrations/webflow_sync.py`, add `import re` to the imports if not already present, then add this constant + function immediately after `FIELD_MAP_PATTERNS` (before `resolve_field_mapping`):

```python
# Match the trailing numeric ID in a MilAnuncios listing URL:
# https://www.milanuncios.com/.../slug-{ID}.htm
_LISTING_ID_RE = re.compile(r"-(\d+)\.htm$")


def _extract_listing_id(url: str | None) -> str | None:
    """Extract the trailing numeric listing ID from a MilAnuncios URL.

    Returns None for empty input, None for URLs without a trailing
    `-{digits}.htm`. Used to key the Webflow dedup index by the same
    invariant identifier the DB uses (`listings.listing_id`).
    """
    if not url:
        return None
    m = _LISTING_ID_RE.search(url)
    return m.group(1) if m else None
```

- [ ] **Step 1.4: Run the test to verify it passes**

```bash
python3 -m pytest tests/test_webflow_sync.py::TestExtractListingId -v
```

Expected: 6 passed.

- [ ] **Step 1.5: Commit**

```bash
git add integrations/webflow_sync.py tests/test_webflow_sync.py
git commit -m "feat(webflow_sync): add _extract_listing_id regex helper

Extracts the trailing numeric ID from a MilAnuncios listing URL.
Used as the canonical dedup key (matches DB listings.listing_id)
instead of exact URL match.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: Prefer `source` slug in field-map (TDD)

**Files:**
- Modify: `integrations/webflow_sync.py:39-67` (`FIELD_MAP_PATTERNS["url"]`)
- Modify: `tests/test_webflow_sync.py` (`TestSourceUrlTempStashOnGooglePlaceId` class)

- [ ] **Step 2.1: Update existing tests to express the new precedence**

In `tests/test_webflow_sync.py`, replace the `TestSourceUrlTempStashOnGooglePlaceId` class (currently around line 100-129) with this updated version. The test names and intent change to reflect that `source` is now the live schema's real slug:

```python
class TestUrlFieldPrecedence:
    """Live Webflow schema now exposes `source` (PlainText). `google-place-id`
    is kept in the candidate list as a transitional fallback for items not
    yet migrated by scripts/migrate_url_to_source.py."""

    SCHEMA_WITH_SOURCE = [
        {"slug": "name",            "type": "PlainText", "isRequired": True},
        {"slug": "slug",            "type": "PlainText", "isRequired": True},
        {"slug": "google-place-id", "type": "PlainText"},
        {"slug": "source",          "type": "PlainText"},
    ]

    SCHEMA_LEGACY = [
        {"slug": "name",            "type": "PlainText", "isRequired": True},
        {"slug": "slug",            "type": "PlainText", "isRequired": True},
        {"slug": "google-place-id", "type": "PlainText"},
    ]

    def test_url_prefers_source_when_present(self):
        mapping = resolve_field_mapping({"fields": self.SCHEMA_WITH_SOURCE})
        assert mapping.get("url") == "source"

    def test_url_falls_back_to_google_place_id_when_source_missing(self):
        mapping = resolve_field_mapping({"fields": self.SCHEMA_LEGACY})
        assert mapping.get("url") == "google-place-id"

    def test_listing_url_lands_on_source(self):
        row = {
            "listing_id": "1",
            "title": "T",
            "webflow_slug": "t",
            "url": "https://www.milanuncios.com/naves/foo-123.htm",
        }
        mapping = {"title": "name", "url": "source"}
        out = build_field_data(row, mapping, [], self.SCHEMA_WITH_SOURCE)
        assert out["source"] == "https://www.milanuncios.com/naves/foo-123.htm"
```

- [ ] **Step 2.2: Run the updated tests to verify the first one fails**

```bash
python3 -m pytest tests/test_webflow_sync.py::TestUrlFieldPrecedence -v
```

Expected: `test_url_prefers_source_when_present` FAILS — current `FIELD_MAP_PATTERNS["url"]` lists `source-url` first (not in schema) and falls through to `google-place-id`, so mapping returns `"google-place-id"`.

- [ ] **Step 2.3: Update `FIELD_MAP_PATTERNS["url"]`**

In `integrations/webflow_sync.py` around line 61-65, replace the existing block:

```python
    # Until Benedict creates the dedicated `source-url` slug, the MilAnuncios
    # listing URL is parked in `google-place-id` as a temporary stash. See
    # docs/decisions/2026-05-04-source-url-temp-stash.md. The proper Google
    # Place ID is not yet collected (geocoding Phase 2), so the slot is free.
    "url":              ["source-url", "google-place-id", "url", "link", "enlace", "url-origen"],
```

with:

```python
    # New items write the MilAnuncios listing URL to `source` (the slug
    # Benedict created 2026-05-09). `google-place-id` is kept as a
    # transitional fallback for items not yet moved by
    # scripts/migrate_url_to_source.py. Once the back-fill is verified in
    # prod, drop `google-place-id` from this list (see spec
    # docs/superpowers/specs/2026-05-10-source-url-migration-design.md).
    "url":              ["source", "source-url", "google-place-id", "url", "link", "enlace", "url-origen"],
```

- [ ] **Step 2.4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_webflow_sync.py::TestUrlFieldPrecedence -v
```

Expected: 3 passed.

- [ ] **Step 2.5: Commit**

```bash
git add integrations/webflow_sync.py tests/test_webflow_sync.py
git commit -m "feat(webflow_sync): prefer 'source' slug over 'google-place-id'

Live Webflow schema now exposes 'source' (added by Benedict 2026-05-09).
Field-map resolver picks it first; 'google-place-id' kept as a
transitional fallback until scripts/migrate_url_to_source.py back-fills
all existing items.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: Rewrite dedup index to key on listing_id (TDD)

**Files:**
- Modify: `integrations/webflow_sync.py:265-312` (replace `_build_source_url_index`)
- Modify: `tests/test_webflow_sync.py` (add `TestDedupIndexByListingId` class)

- [ ] **Step 3.1: Write the failing test**

Add to `tests/test_webflow_sync.py` (after `TestUrlFieldPrecedence`):

```python
import asyncio
from unittest.mock import AsyncMock

from integrations.webflow_sync import _build_listing_id_index


class TestDedupIndexByListingId:
    """Dedup index uses listing_id (extracted via regex) as the key,
    making it robust to URL canonicalization differences."""

    def _make_client(self, items):
        client = AsyncMock()
        client.list_items = AsyncMock(return_value=items)
        return client

    def test_indexes_items_by_listing_id(self):
        items = [
            {"id": "item-a", "fieldData": {"source": "https://www.milanuncios.com/x/foo-111.htm"}},
            {"id": "item-b", "fieldData": {"source": "https://www.milanuncios.com/x/bar-222.htm"}},
        ]
        client = self._make_client(items)
        mapping = {"url": "source"}
        index = asyncio.run(_build_listing_id_index(client, mapping, None))
        assert index == {"111": "item-a", "222": "item-b"}

    def test_skips_non_url_values(self):
        # A real Google Place ID accidentally written to the slot must
        # not corrupt the index.
        items = [
            {"id": "item-a", "fieldData": {"source": "ChIJN1t_tDeuEmsRUsoyG83frY4"}},
            {"id": "item-b", "fieldData": {"source": "https://www.milanuncios.com/x/foo-333.htm"}},
        ]
        client = self._make_client(items)
        mapping = {"url": "source"}
        index = asyncio.run(_build_listing_id_index(client, mapping, None))
        assert index == {"333": "item-b"}

    def test_skips_urls_without_listing_id(self):
        items = [
            {"id": "item-a", "fieldData": {"source": "https://www.milanuncios.com/naves/"}},
            {"id": "item-b", "fieldData": {"source": "https://www.milanuncios.com/x/foo-444.htm"}},
        ]
        client = self._make_client(items)
        mapping = {"url": "source"}
        index = asyncio.run(_build_listing_id_index(client, mapping, None))
        assert index == {"444": "item-b"}

    def test_returns_empty_when_no_url_slug_mapped(self):
        client = self._make_client([])
        index = asyncio.run(_build_listing_id_index(client, {}, None))
        assert index == {}

    def test_returns_empty_when_list_items_fails(self):
        client = AsyncMock()
        client.list_items = AsyncMock(side_effect=RuntimeError("network"))
        index = asyncio.run(_build_listing_id_index(client, {"url": "source"}, None))
        assert index == {}
```

- [ ] **Step 3.2: Run the test to verify it fails**

```bash
python3 -m pytest tests/test_webflow_sync.py::TestDedupIndexByListingId -v
```

Expected: `ImportError: cannot import name '_build_listing_id_index'`.

- [ ] **Step 3.3: Remove the superseded `TestBuildSourceUrlIndex` class**

In `tests/test_webflow_sync.py`, delete the existing `_StubClient` helper class and `TestBuildSourceUrlIndex` class (currently around lines 313-355 — search for `class TestBuildSourceUrlIndex:` and remove that class and the `_StubClient` it uses). Also remove the now-unused import `_build_source_url_index` from the file's top-level imports.

The behaviors the old class tested (empty-when-no-mapping, indexes items, swallows errors) are all asserted by the new `TestDedupIndexByListingId` class added in Step 3.1.

- [ ] **Step 3.4: Replace `_build_source_url_index` with `_build_listing_id_index`**

In `integrations/webflow_sync.py` around line 265-312, replace the entire `_build_source_url_index` function with:

```python
async def _build_listing_id_index(
    client: WebflowClient,
    field_mapping: dict[str, str],
    cms_locale_id: str | None,
) -> dict[str, str]:
    """Return {listing_id: item_id} from existing Webflow items.

    Reads from whichever slug the field-map resolved for `url`
    (`source` once live; `google-place-id` for legacy items during the
    migration window). Values are filtered to http(s)-shaped URLs and
    further filtered to those exposing a trailing numeric listing ID
    (see _extract_listing_id). Foreign or malformed values are silently
    skipped so they cannot corrupt the index.

    Empty when the collection has no `url`-style mapped slug, or when
    list_items fails — we lose the dedup safety net for that run but
    never fail the sync because of it.
    """
    source_slug = field_mapping.get("url")
    if not source_slug:
        logger.info(
            "[Webflow] No url-style field mapped; skipping dedup index "
            "(sync will create items without checking for duplicates)."
        )
        return {}

    try:
        items = await client.list_items(cms_locale_id=cms_locale_id)
    except Exception as e:
        logger.warning(
            "[Webflow] list_items failed; skipping dedup index this run: %s", e
        )
        return {}

    index: dict[str, str] = {}
    for item in items:
        field_data = item.get("fieldData", {}) or {}
        raw = field_data.get(source_slug)
        if not raw:
            continue
        value = str(raw).strip()
        if not value.startswith(("http://", "https://")):
            continue
        listing_id = _extract_listing_id(value)
        if not listing_id:
            continue
        index[listing_id] = item.get("id", "")
    logger.info(
        "[Webflow] Dedup index built: %d items keyed by listing_id "
        "(from slug=%s)", len(index), source_slug,
    )
    return index
```

- [ ] **Step 3.5: Run the test to verify it passes**

```bash
python3 -m pytest tests/test_webflow_sync.py::TestDedupIndexByListingId -v
```

Expected: 5 passed.

- [ ] **Step 3.6: Commit**

```bash
git add integrations/webflow_sync.py tests/test_webflow_sync.py
git commit -m "feat(webflow_sync): dedup index keyed by listing_id instead of URL

Replaces _build_source_url_index with _build_listing_id_index. The index
now keys on the regex-extracted listing ID (matches DB primary key),
making it survive URL canonicalization changes (http/https, www, trailing
slash, slug edits) which the prior exact-string comparison did not.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: Update per-row dedup check in `sync_pending_listings`

**Files:**
- Modify: `integrations/webflow_sync.py:361-381` (the per-row dedup block inside `sync_pending_listings`)
- Modify: `tests/test_webflow_sync.py` (add `TestSyncSkipsExistingListingId`)

- [ ] **Step 4.1: Write the failing E2E test**

Add to `tests/test_webflow_sync.py`:

```python
from unittest.mock import patch, AsyncMock, MagicMock

from integrations.webflow_sync import sync_pending_listings


class TestSyncSkipsExistingListingId:
    """E2E: when a pending DB row's listing_id already exists in the CMS,
    sync adopts the existing item_id and skips creation (no POST)."""

    def test_existing_listing_id_short_circuits_creation(self, monkeypatch, tmp_path):
        # Arrange: one pending row whose listing_id matches an existing CMS item
        pending_row = {
            "listing_id": "999",
            "url": "https://www.milanuncios.com/x/foo-999.htm",
            "title": "Test Warehouse",
            "webflow_slug": "test-warehouse",
        }

        existing_cms_item = {
            "id": "wf-item-existing",
            "fieldData": {"source": "https://www.milanuncios.com/x/foo-999.htm"},
        }

        # Mock WebflowClient: schema, list_items, resolve_spanish_locale_id
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get_collection_schema = AsyncMock(return_value={
            "fields": [
                {"slug": "name",   "type": "PlainText", "isRequired": True},
                {"slug": "slug",   "type": "PlainText", "isRequired": True},
                {"slug": "source", "type": "PlainText"},
            ],
        })
        mock_client.list_items = AsyncMock(return_value=[existing_cms_item])
        mock_client.resolve_spanish_locale_id = AsyncMock(return_value=None)
        # Trip-wire: if creation ever runs, the test must fail loudly.
        mock_client.create_item = AsyncMock(
            side_effect=AssertionError("create_item must not be called"),
        )

        monkeypatch.setenv("WEBFLOW_TOKEN", "fake")
        monkeypatch.setenv("WEBFLOW_COLLECTION_ID", "fake")

        # Patch DB-side helpers and the WebflowClient class
        with patch("integrations.webflow_sync.get_unsynced_listings", return_value=[pending_row]), \
             patch("integrations.webflow_sync.update_webflow_id") as mock_update, \
             patch("integrations.webflow_sync.WebflowClient", return_value=mock_client), \
             patch("integrations.webflow_sync.sqlite3.connect", return_value=MagicMock()):

            result = asyncio.run(sync_pending_listings())

        # Assert: synced=1, no creation attempted, update_webflow_id called
        # with the existing CMS item ID
        assert result["synced"] == 1
        assert result["failed"] == 0
        mock_update.assert_called_once()
        called_args = mock_update.call_args[0]
        assert called_args[1] == "999"                # listing_id
        assert called_args[2] == "wf-item-existing"   # existing CMS id
```

- [ ] **Step 4.2: Run the test to verify it fails**

```bash
python3 -m pytest tests/test_webflow_sync.py::TestSyncSkipsExistingListingId -v
```

Expected: FAIL — current dedup code reads `row_url in source_url_index` (URL key), and the index now uses listing_id keys, so the row falls through to creation and `mock_client.create_item` raises AssertionError.

- [ ] **Step 4.3: Update the per-row dedup block**

In `integrations/webflow_sync.py`, find the block around line 356-381 that builds `source_url_index` and per-row checks `row_url in source_url_index`. Replace with:

```python
            # Iteración 2026-05 (Tarea 6) + 2026-05-10 source-url migration:
            # Build a {listing_id: item_id} index from the existing CMS items
            # so we can short-circuit creation when the listing was already
            # synced (or exists as a leftover draft from a previous run).
            # The index is a no-op when the schema has no url-style slug.
            listing_id_index = await _build_listing_id_index(
                client, field_mapping, spanish_locale_id,
            )

            logger.info("[Webflow] Iniciando sync: %d anuncios pendientes", len(rows))

            for row in rows:
                listing_id = row.get("listing_id", "")

                # Webflow-side dedup: if an existing item already references
                # this listing_id, adopt its item_id and skip creation.
                if listing_id_index and listing_id and listing_id in listing_id_index:
                    existing_id = listing_id_index[listing_id]
                    update_webflow_id(conn, listing_id, existing_id)
                    synced += 1
                    logger.info(
                        "[SKIP-WEBFLOW] %s ya existe como %s (listing_id match)",
                        listing_id, existing_id,
                    )
                    continue
```

(The block continues with the existing image-upload + create-item logic — leave those lines untouched.)

- [ ] **Step 4.4: Run the test to verify it passes**

```bash
python3 -m pytest tests/test_webflow_sync.py::TestSyncSkipsExistingListingId -v
```

Expected: 1 passed.

- [ ] **Step 4.5: Run the full webflow_sync test suite to check no regressions**

```bash
python3 -m pytest tests/test_webflow_sync.py -v
```

Expected: all tests in the file pass.

- [ ] **Step 4.6: Commit**

```bash
git add integrations/webflow_sync.py tests/test_webflow_sync.py
git commit -m "feat(webflow_sync): dedup pending rows by listing_id

sync_pending_listings now short-circuits creation when row.listing_id is
already in the CMS, replacing the prior exact-URL comparison. Covered by
an E2E test that asserts no create_item is called on a duplicate row.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Back-fill script `scripts/migrate_url_to_source.py` (TDD)

**Files:**
- Create: `scripts/migrate_url_to_source.py`
- Create: `tests/test_migrate_url_to_source.py`

- [ ] **Step 5.1: Write the failing tests**

Create `tests/test_migrate_url_to_source.py` with:

```python
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

    assert summary == {"moved": 1, "skipped_empty": 0, "skipped_non_milanuncios": 0, "failed": 0}
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
            "google-place-id": "ChIJN1t_tDeuEmsRUsoyG83frY4",  # real Place ID
            "source": "",
        },
    }]
    client = AsyncMock()
    client.list_items = AsyncMock(return_value=items)
    client.update_items = AsyncMock()

    summary = await migrate_items(client, cms_locale_id=None, dry_run=False)

    assert summary == {"moved": 0, "skipped_empty": 0, "skipped_non_milanuncios": 1, "failed": 0}
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

    assert summary == {"moved": 0, "skipped_empty": 1, "skipped_non_milanuncios": 0, "failed": 0}
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
```

- [ ] **Step 5.2: Run the tests to verify they fail**

```bash
python3 -m pytest tests/test_migrate_url_to_source.py -v
```

Expected: `ModuleNotFoundError: No module named 'scripts.migrate_url_to_source'`.

- [ ] **Step 5.3: Create the migration script**

Create `scripts/migrate_url_to_source.py`:

```python
"""One-shot back-fill: move MilAnuncios listing URLs from `google-place-id`
to the new `source` field in Webflow CMS, then clear the old slot.

Usage:
    python scripts/migrate_url_to_source.py [--dry-run] [--limit N] [--verbose]

Exit codes:
    0  Clean run, no failures
    1  Partial: at least one item failed during PATCH
    2  Configuration error (missing token / collection id)
"""
import argparse
import asyncio
import logging
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from integrations.webflow_client import WebflowClient, COLLECTION_ID, WEBFLOW_TOKEN

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("migrate_url_to_source")

_MILANUNCIOS_URL_RE = re.compile(r"^https?://(www\.)?milanuncios\.com/", re.IGNORECASE)


async def migrate_items(
    client: WebflowClient,
    cms_locale_id: str | None,
    dry_run: bool,
    limit: int | None = None,
) -> dict[str, int]:
    """Walk all CMS items and migrate matching ones.

    Returns counters: {moved, skipped_empty, skipped_non_milanuncios, failed}.
    """
    items = await client.list_items(cms_locale_id=cms_locale_id)
    if limit is not None:
        items = items[:limit]

    moved = 0
    skipped_empty = 0
    skipped_non_milanuncios = 0
    failed = 0

    pending_updates: list[dict] = []

    for item in items:
        item_id = item.get("id", "")
        field_data = item.get("fieldData", {}) or {}
        raw = field_data.get("google-place-id", "")
        value = str(raw).strip() if raw else ""

        if not value:
            skipped_empty += 1
            continue

        if not _MILANUNCIOS_URL_RE.match(value):
            skipped_non_milanuncios += 1
            logger.debug(
                "[MIGRATE] item=%s skipped (non-milanuncios value: %r)",
                item_id, value[:60],
            )
            continue

        logger.info("[MIGRATE] item=%s would move: %s", item_id, value)
        pending_updates.append({
            "id": item_id,
            "fieldData": {"source": value, "google-place-id": ""},
        })
        moved += 1

    if not dry_run and pending_updates:
        result = await client.update_items(pending_updates, cms_locale_id=cms_locale_id)
        if result.get("errors"):
            failed = moved - result.get("updated", 0)
            moved = result.get("updated", 0)
            for err in result["errors"]:
                logger.error("[MIGRATE] update error: %s", err)

    return {
        "moved": moved,
        "skipped_empty": skipped_empty,
        "skipped_non_milanuncios": skipped_non_milanuncios,
        "failed": failed,
    }


async def main_async(args: argparse.Namespace) -> int:
    if not WEBFLOW_TOKEN or not COLLECTION_ID:
        logger.error(
            "WEBFLOW_TOKEN or WEBFLOW_COLLECTION_ID missing in environment"
        )
        return 2

    async with WebflowClient() as client:
        cms_locale_id = await client.resolve_spanish_locale_id()
        summary = await migrate_items(
            client, cms_locale_id=cms_locale_id,
            dry_run=args.dry_run, limit=args.limit,
        )

    logger.info(
        "[MIGRATE] moved=%d skipped_empty=%d skipped_non_milanuncios=%d failed=%d",
        summary["moved"], summary["skipped_empty"],
        summary["skipped_non_milanuncios"], summary["failed"],
    )
    return 1 if summary["failed"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be migrated without writing")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process at most N items (for testing)")
    parser.add_argument("--verbose", action="store_true",
                        help="Enable DEBUG logging")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5.4: Run the tests to verify they pass**

```bash
python3 -m pytest tests/test_migrate_url_to_source.py -v
```

Expected: 4 passed.

(`pytest-asyncio` is already installed in this environment and other tests in `test_webflow_sync.py` use the same `@pytest.mark.asyncio` pattern — no setup needed.)

- [ ] **Step 5.5: Commit**

```bash
git add scripts/migrate_url_to_source.py tests/test_migrate_url_to_source.py
git commit -m "feat(scripts): migrate_url_to_source.py back-fill CMS items

Walks every Webflow CMS item, finds those with a MilAnuncios URL stashed
in google-place-id, and PATCHes them to put the URL in the new 'source'
slug (clearing google-place-id). Supports --dry-run and --limit.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Full-suite verification

**Files:** None (verification only).

- [ ] **Step 6.1: Run the entire test suite**

```bash
python3 -m pytest tests/ -v
```

Expected: 112 prior tests + 5 new tests = 117 (or near — exact count may shift if any existing tests touched the old `_build_source_url_index` import). All pass.

If any prior test fails because it imported `_build_source_url_index` directly, search and replace:

```bash
grep -rn "_build_source_url_index" tests/ integrations/ scripts/
```

Update any caller to `_build_listing_id_index`. The function takes the same arguments; only the return shape changed from `{url: item_id}` to `{listing_id: item_id}` — only `sync_pending_listings` consumed it.

- [ ] **Step 6.2: Run the live Webflow schema inspector as a sanity probe**

```bash
python3 scripts/inspect_webflow_schema.py
```

Expected: the `source` slug appears in the field list, `[FOUND] Source URL` won't appear (the inspector still searches the old candidate list), but the raw schema dump confirms `source` is present.

- [ ] **Step 6.3: Commit (no code changes — checkpoint only if Step 6.1 required fixes)**

If Step 6.1 required edits:

```bash
git add tests/ integrations/ scripts/
git commit -m "fix: align stale callers with _build_listing_id_index rename

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: Resolve the temp-stash decision doc

**Files:**
- Modify: `docs/decisions/2026-05-04-source-url-temp-stash.md` (append Resolved footer)

- [ ] **Step 7.1: Append a Resolved section at the end of the decision doc**

Add the following to the bottom of `docs/decisions/2026-05-04-source-url-temp-stash.md`:

```markdown

---

## Resolution (2026-05-10)

Benedict added the `source` slug to the Webflow collection on 2026-05-09.
The migration is implemented in:

- Code: `integrations/webflow_sync.py` (`FIELD_MAP_PATTERNS["url"]` now
  lists `source` first; `_build_listing_id_index` replaces the old
  URL-keyed index; per-row dedup compares `listing_id`).
- Back-fill: `scripts/migrate_url_to_source.py` (one-shot, run after
  scheduler pause).
- Spec: `docs/superpowers/specs/2026-05-10-source-url-migration-design.md`.

Status: **Resolved**. `google-place-id` is still in the candidate list
as a transitional fallback; remove it in a follow-up PR once the
back-fill has run cleanly in prod.
```

- [ ] **Step 7.2: Commit**

```bash
git add docs/decisions/2026-05-04-source-url-temp-stash.md
git commit -m "docs: mark source-url temp-stash decision as resolved

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Rollout (operational — not part of the implementation tasks)

After all tasks above are merged to `main`:

1. **Pause the scheduler.** `curl -X POST -H "x-api-key: $API_KEY" http://VPS:8000/api/cron/pause` (or use the Programación tab). Prevents the daily scrape from creating duplicates of un-migrated items during the migration window.
2. **Dry-run the back-fill** against prod Webflow:
   ```bash
   python scripts/migrate_url_to_source.py --dry-run
   ```
   Review the `[MIGRATE]` log lines and the summary counters.
3. **Run the real back-fill:**
   ```bash
   python scripts/migrate_url_to_source.py
   ```
   Spot-check 3-5 items in the Webflow editor to confirm `source` is populated and `google-place-id` is empty.
4. **Resume the scheduler.** `curl -X POST -H "x-api-key: $API_KEY" http://VPS:8000/api/cron/resume`.
5. **Final cleanup (separate PR):** Once a sync cycle has run cleanly, remove `"google-place-id"` from `FIELD_MAP_PATTERNS["url"]` candidates.

---

## Self-Review Notes

- **Spec coverage:** Field-map precedence (Task 2), listing-id helper (Task 1), dedup index rewrite (Task 3), per-row dedup (Task 4), back-fill script (Task 5), 5 tests (Tasks 1+3+4+5 cover all 5 spec test cases), decision-doc resolution (Task 7), rollout steps (Rollout section). All spec requirements covered.
- **Placeholders:** None.
- **Type consistency:** Helper name `_extract_listing_id` and index name `_build_listing_id_index` consistent across tasks. The renamed-from `_build_source_url_index` is grep-checked in Task 6.
- **Test count:** Task 1 (6 sub-tests in one class), Task 2 (3), Task 3 (5), Task 4 (1), Task 5 (4). The "5 test scrapes" the user asked for map to: regex (1 class), field-map (1 class), dedup index (1 class), sync E2E (1 class), back-fill (1 class) = 5 scenario classes covering 19 individual assertions.
