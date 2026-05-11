# Source URL migration & listing-id dedup — Design

**Date:** 2026-05-10
**Status:** Draft
**Owner:** Alejandro
**Triggered by:** Benedict's email (2026-05-09) — move URL to the new `Source`
field in Webflow CMS, back-fill existing items, harden dedup.

## Context

Benedict added a new `Source` field (slug `source`, PlainText) to the
Spain Warehouses Webflow collection. The codebase already anticipated this
migration via `docs/decisions/2026-05-04-source-url-temp-stash.md` — the
MilAnuncios listing URL has been parked in `google-place-id` while the proper
slug was missing. Today's live schema inspection
(`docs/webflow-schema.json`) confirms `source` now exists, alongside the
still-present `google-place-id` slot.

The existing dedup machinery (`_build_source_url_index` +
per-row check in `sync_pending_listings`) compares exact URL strings. That
fails the moment a URL is canonicalized differently
(http/https, `www.`, trailing slash, location-slug edits). The MilAnuncios
URL embeds an immutable trailing numeric listing ID — the same value we
already store as the DB primary key (`listings.listing_id`). Using that ID
as the dedup key, extracted via a simple regex, is strictly more robust.

## Goals

1. New scrapes write the MilAnuncios URL to `source` in Webflow.
2. Every sync builds a `{listing_id: item_id}` index from the live CMS and
   short-circuits creation when the listing already exists.
3. One-shot back-fill: for every existing CMS item whose `google-place-id`
   value is a MilAnuncios URL, copy it to `source` and clear
   `google-place-id`.
4. Coverage: 5 pytest cases over the regex, field-map, dedup index, sync
   E2E, and back-fill function.

## Non-Goals

- Re-scraping existing listings to recover phones or contact data.
- Adding any other field, schema migration, or scraper-side change.
- Geocoding / Google Place ID collection (still Phase 2).
- Removing `google-place-id` from `FIELD_MAP_PATTERNS["url"]` candidates —
  kept as a transitional fallback until the back-fill is verified in prod.

## Architecture

Single sync path, single dedup path. No new modules; one new one-shot
script.

```
scraper_engine.run()
   └─► insert_listing (DB)
            ↓
   integrations.webflow_sync.sync_pending_listings()
            ├─ resolve_field_mapping(schema)        # picks `source` first
            ├─ _build_listing_id_index(client, …)   # {listing_id: item_id}
            └─ for row in pending:
                    if row.listing_id in index:    [SKIP-WEBFLOW]
                    else: create CMS item with source=row.url
```

One-shot back-fill (manual, run once after sync hits prod):

```
scripts/migrate_url_to_source.py
   ├─ client.list_items(cms_locale_id=…)
   └─ for item in items:
         gpi = field_data['google-place-id']
         if gpi matches ^https?://(www\.)?milanuncios\.com/
             client.patch_item(id, {source: gpi, google-place-id: ""})
```

## Components

### 1. `integrations/webflow_sync.py`

**a. Field-map precedence.** Prepend `"source"` to `FIELD_MAP_PATTERNS["url"]`:

```python
"url": ["source", "source-url", "google-place-id", "url", "link", "enlace", "url-origen"],
```

`resolve_field_mapping` walks the candidate list left-to-right; the first
slug present in the live schema wins. Today that yields `source`. During
the migration window before the back-fill runs, items not yet migrated
still have their URL on `google-place-id`, but the dedup index will
read it through the resolved slug (which is `source` now) — meaning
un-migrated items are temporarily invisible to dedup. **This is the
expected and intentional behavior**: it is the back-fill's job to close
that gap. Newly scraped duplicates of un-migrated items will be re-created
in the CMS until the back-fill runs once.

**b. Listing-ID extraction.**

```python
_LISTING_ID_RE = re.compile(r"-(\d+)\.htm$")

def _extract_listing_id(url: str) -> str | None:
    m = _LISTING_ID_RE.search(url or "")
    return m.group(1) if m else None
```

Module-level constant, single regex compile.

**c. Dedup index.** Rename `_build_source_url_index` → `_build_listing_id_index`,
return `{listing_id: item_id}`. Preserves the existing
http(s)-shape guard; additionally requires a successful listing-ID extract
before indexing.

**d. Per-row dedup.** Replace the `row_url in source_url_index` check with
`listing_id in listing_id_index`. The listing_id is already on `row`
(it's the DB primary key passed through `get_unsynced_listings`).

### 2. `scripts/migrate_url_to_source.py` (new)

CLI signature:

```
python scripts/migrate_url_to_source.py [--dry-run] [--limit N] [--verbose]
```

Behavior:
- Auth pre-flight: aborts with exit 2 if `WEBFLOW_TOKEN` or
  `WEBFLOW_COLLECTION_ID` is missing.
- Resolves the Spanish locale (same call as `webflow_sync`).
- Paginates all items via `WebflowClient.list_items`.
- For each item, reads `field_data["google-place-id"]`. If the value
  matches `^https?://(www\.)?milanuncios\.com/` → PATCH the item with
  `{"source": gpi, "google-place-id": ""}`, preserving `isDraft` /
  `isArchived`. Other values are left untouched.
- Counters: `moved`, `skipped_empty`, `skipped_non_milanuncios`, `failed`.
- Summary on exit:
  `[MIGRATE] moved=N skipped_empty=N skipped_non_milanuncios=N failed=N`.
- Exit codes: `0` clean run, `1` partial (any `failed > 0`), `2`
  config/auth error.

`--dry-run` performs all reads and the URL-shape check; logs what *would*
be patched; no writes.

### 3. Tests

| # | File | Test | Mocked |
|---|---|---|---|
| 1 | `tests/test_webflow_sync.py` | `test_extract_listing_id_variants` | n/a (pure function) |
| 2 | `tests/test_webflow_sync.py` | `test_field_map_resolves_source_first` | schema dict |
| 3 | `tests/test_webflow_sync.py` | `test_dedup_index_by_listing_id` | `WebflowClient.list_items` |
| 4 | `tests/test_webflow_sync.py` | `test_sync_skips_existing_listing_id` | `WebflowClient` (full) |
| 5 | `tests/test_migrate_url_to_source.py` | `test_backfill_moves_only_milanuncios_urls` (parametrized: matching URL → patched; non-URL → skipped) | `WebflowClient.list_items` + `patch_item` |

All tests use the existing `mem_db` / `tmp_path` patterns from
`tests/conftest.py`. No network. No real Webflow calls.

## Data Flow

**Sync.**

```
DB (listings table)        Webflow CMS                       Disk
   │                            │
   │  get_unsynced_listings()   │
   ├──────────────────────────► │
   │                            │  GET /collections/.../items
   │                            ├──── build {lid: item_id} ─►
   │  for row in rows:          │
   │    if lid in index:        │
   │      update_webflow_id ◄───┤  (no API call)
   │    else:                   │  POST /collections/.../items
   │      create item ─────────►│   field_data.source = row.url
   │      update_webflow_id ◄───┤
```

**Back-fill.**

```
Webflow CMS                          Webflow CMS
   │                                       │
   │  GET items (paginate) ─────────────►  │
   │  for each: regex(google-place-id)     │
   │    if match: PATCH item ───────────►  │ source = old gpi
   │                                       │ google-place-id = ""
```

## Error Handling

Mirrors the existing per-item resilience in `sync_pending_listings`:

| Failure | Behavior |
|---|---|
| Listing-ID regex fails on a CMS item | Skip indexing, log debug, dedup falls through to "create new item" path (creates duplicate; acceptable rare case) |
| `list_items` 5xx during index build | Index is empty → entire run loses dedup safety; log warning, continue sync (existing behavior) |
| `patch_item` fails during back-fill | Counter++, log warning with item id, continue |
| Auth/config missing | Migration script exits 2 (no partial writes); sync logs warning and skips (existing behavior) |
| `field_data["google-place-id"]` is None / wrong type | Treat as empty, skip |

## Testing

5 pytest cases, listed in Components → Tests. No network. Existing
fixtures only. Run:

```
python3 -m pytest tests/test_webflow_sync.py tests/test_migrate_url_to_source.py -v
```

Plus the full suite must remain green: `python3 -m pytest tests/ -v`.

## Observability

- `[Webflow] Dedup index built: N items with listing_id` (replaces the
  `source-url` log line).
- `[SKIP-WEBFLOW] {listing_id} ya existe como {item_id} (listing_id match)`
  (existing marker, message updated).
- `[MIGRATE] item={id} moved` per migrated item in the back-fill.
- `[MIGRATE] moved=N skipped_empty=N skipped_non_milanuncios=N failed=N`
  summary on script exit.

## Rollout

1. Land the `webflow_sync.py` changes + tests. Sync now writes to `source`
   for new items; dedups by listing_id within the `source` slot.
2. **Pause the scheduler** (`POST /api/cron/pause` or `--pages 0` toggle)
   to prevent a scheduled scrape from running in the migration window —
   un-migrated items would be invisible to dedup and risk duplicate
   creation.
3. Run `python scripts/migrate_url_to_source.py --dry-run` against
   production Webflow; review counters.
4. Run without `--dry-run`. Verify a sample of CMS items in the Webflow
   editor.
5. Resume the scheduler.
6. After one full sync cycle confirms no regressions, remove
   `"google-place-id"` from `FIELD_MAP_PATTERNS["url"]` candidates and
   mark `docs/decisions/2026-05-04-source-url-temp-stash.md` as Resolved
   with a link to the back-fill commit. (Separate small PR; out of scope
   for this design.)

## References

- `integrations/webflow_sync.py:39-67` — `FIELD_MAP_PATTERNS`
- `integrations/webflow_sync.py:265-312` — `_build_source_url_index`
- `integrations/webflow_sync.py:361-381` — per-row dedup check
- `docs/decisions/2026-05-04-source-url-temp-stash.md` — original temp-stash decision
- `docs/webflow-schema.json` — live schema snapshot (regenerated 2026-05-10)
- Benedict's email thread (2026-05-09, "Source field" + "backtrack existing warehouses")
