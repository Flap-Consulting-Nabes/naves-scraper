# Slug System — Title-Based Unique Slugs

Status: `[IMPLEMENTED]`
Owner: Alejandro
Date: 2026-04-07

## Purpose

Replace the listing-id-based slug (`nave-123456789`) with a title-based slug
(`nave-industrial-madrid-1000m2`) that is:

1. Computed **once** at scrape time and stored on the listing row
2. Reused verbatim for the Webflow CMS page slug **and** the local image filenames
3. Guaranteed unique across all listings via a numeric suffix when titles collide

## Contract

### Slug field
- Stored in `listings.webflow_slug TEXT UNIQUE-ish` (SQLite does not enforce
  uniqueness at the schema level here, but the generator enforces it).
- Indexed via `idx_webflow_slug` for the collision lookup.

### Generation rules (`utils/slugify.py`)

```python
slugify_title(title: str | None, listing_id: str, max_length: int = 75) -> str
```

1. NFKD normalise → strip accents (`Náve` → `Nave`, `ñ` → `n`)
2. Lowercase, replace `[^a-z0-9]+` with `-`, collapse `--+`, strip leading/trailing `-`
3. Truncate to `max_length` (75) — reserves 5 chars for a `-NNN` suffix
4. Empty title → fallback `nave-{listing_id}` (listing_id is already unique)

```python
generate_unique_slug(conn, title, listing_id, exclude_listing_id=None) -> str
```

1. `base = slugify_title(title, listing_id)`
2. Query `listings.webflow_slug` for anything matching `base` or `base-<n>`,
   excluding a given listing_id (migration re-computes a row's own slug).
3. No collision → return `base`
4. Collision → scan the returned slugs for numeric suffixes, return
   `f"{base}-{max(suffixes, default=1) + 1}"`
5. First duplicate therefore gets `-2`, second gets `-3`, etc.

### Consumers
- `scraper_engine.run()` — computes the slug **before** calling
  `insert_listing()` so the row is persisted with its slug in one transaction.
- `utils/image_downloader.download_images()` — takes the final slug and writes
  files as `{slug}-image-{i}.{ext}` under `images/{listing_id}/`.
- `integrations/webflow_sync.build_field_data()` — sets
  `field_data["slug"] = row["webflow_slug"]` with `nave-{listing_id}` fallback.

### Webflow re-sync (`integrations/webflow_client.update_items`)
Batches PATCH `/v2/collections/{collection_id}/items` with up to 100
`{"id": ..., "fieldData": {...}}` entries per request. Used by the migration
script to back-port existing items.

## Migration (`scripts/migrate_slugs.py`)

Idempotent, five phases with `--dry-run`, `--skip-webflow`, `--skip-images`:

| Phase | What it does |
|---|---|
| A | `init_db()` — adds `webflow_slug` column via existing `_NEW_COLUMNS` path |
| B | For every row with `webflow_slug IS NULL` (oldest first by `scraped_at ASC`), compute and store the unique slug |
| C | For every row with `images_local`, rename `{listing_id}/*.ext` files to `{slug}-image-{i}.{ext}` and rewrite the JSON path array |
| D | For every row with a real `webflow_item_id`, PATCH Webflow in batches of 100 with `{"slug": row["webflow_slug"]}` |
| E | `UPDATE listings SET webflow_item_id = NULL WHERE webflow_item_id = 'DUPLICATE'` — old silent markers are now re-processed fresh |

Re-runs are safe: each phase checks current state before writing.

## Risks

| Risk | Mitigation |
|---|---|
| Empty title | Fallback `nave-{listing_id}` — always unique |
| Very long title | Truncated to 75 chars before suffix |
| Image missing on disk | Log + skip, leave DB entry as-is |
| Rename target exists | Skip (assume prior run) |
| Webflow 404 on PATCH | Clear `webflow_item_id` → normal create on next sync |
| Webflow 409 on PATCH | Log + leave unsynced for investigation |
| Interrupted migration | Each phase idempotent |
| Live Webflow URL break | Explicitly accepted by user (re-sync everything) |

## Non-goals
- Splitting `scraper_engine.py` / `db.py` further
- Dashboard UI changes
- Re-uploading image assets to Webflow CDN
- Adding a test suite (codebase has none today)
