# Image Compression + Webflow Asset Upload Fix

Status: `[IMPLEMENTED]`
Owner: Alejandro
Date: 2026-04-07 · updated 2026-04-08 (Cloudinary staging host)

## Purpose

Two tightly-coupled goals, both visible to the end reader of the Webflow blog:

1. **Shrink blog images** to ≤80 KB each. 80 files currently exceed 80 KB on
   disk, 7 exceed 100 KB, largest is 511 KB. MilAnuncios bytes are written
   verbatim with zero compression today.
2. **Fix Webflow filenames** so CMS items show `{slug}-image-{i}.webp`
   instead of Webflow-assigned UUID hashes (`5096e98f…7c522.webp`). Root
   cause: `WEBFLOW_TOKEN` lacks `assets:read` / `assets:write`, so every
   item ever synced took the silent fallback at `webflow_sync.py:215-222`
   which passes remote MilAnuncios URLs to Webflow and lets Webflow re-host
   them with hash-based names.

The already-implemented title-based slug system
(`docs/plans/slug-system.md`) takes care of the filename stems — this
plan closes the loop: compress to WebP, upload via the Assets API, keep
the slug-based names intact on Webflow's CDN.

## Contract

### Compressor (`utils/image_compressor.py`)

```python
compress_to_webp(
    src: bytes | Path,
    dst: Path,
    quality: int = 80,
    max_dim: int = 1200,
) -> int
```

1. Load from bytes or path (Pillow `Image.open(BytesIO(...))` or direct path).
2. Convert `RGBA` / `P` / `LA` → `RGB` so WebP can encode without alpha
   issues (listings never need transparency).
3. `thumbnail((max_dim, max_dim), LANCZOS)` — preserves aspect ratio,
   only shrinks, never upscales.
4. `save(dst, "WEBP", quality=80, method=6)`. `method=6` is the slowest
   / highest-quality WebP encoder — acceptable for a once-per-image
   operation.
5. Returns the final file size in bytes.

Defaults chosen for the "balanced" profile after user confirmation:
`quality=80`, `max_dim=1200`. Produces ~40–70 KB per listing image in
practice, well under the 80 KB target.

### Download-time integration (`utils/image_downloader.py`)

- All new listings go through `compress_to_webp()` in-memory between the
  `requests.get()` call and the disk write.
- Output filename is **always** `{slug}-image-{i}.webp` — the legacy
  extension-inference block (`jpg`/`png`/`webp`/`gif` from URL) is
  removed.
- The old `_download_one_image()` helper is deleted; the loop now handles
  download + compress + save inline.

### Webflow content-type fix (`integrations/webflow_client.py`)

`upload_asset()` used to hardcode `image/jpeg` whenever `uploadDetails`
did not provide a `Content-Type`. S3 pre-signed uploads reject files
whose content-type does not match the signed content-type. Patch:

```python
ext = Path(filename).suffix.lower().lstrip(".")
default_ct = {
    "webp": "image/webp",
    "png":  "image/png",
    "gif":  "image/gif",
}.get(ext, "image/jpeg")
content_type = upload_details.get("Content-Type", default_ct)
```

### Image upload fallback chain

Extracted to `integrations/webflow_image_uploader.py` (keeps
`webflow_sync.py` under the 300-line cap). For every local WebP of a
listing, the uploader tries three paths in order until one hosts the
image publicly:

1. **Webflow Assets API** (`client.upload_asset`) — native, ideal.
   Returns a slug-based CDN URL. Fails silently with HTTP 403 while
   `WEBFLOW_TOKEN` lacks `assets:read` / `assets:write`.
2. **Cloudinary staging host** (`integrations/cloudinary_client.upload_image`)
   — uploads to `cloudinary.com/.../milanuncions/{slug}-image-{i}` with
   a deterministic `public_id` equal to the slug-based filename stem.
   Webflow then downloads that URL and re-hosts the file on its own CDN
   under the same last-path-segment basename, so the end-reader sees
   `{asset-id}_{slug}-image-{i}.webp` — SEO-friendly. Requires
   `CLOUDINARY_CLOUD_NAME` / `CLOUDINARY_API_KEY` / `CLOUDINARY_API_SECRET`
   env vars; returns `None` cleanly if they are missing.
3. **Raw MilAnuncios remote URL** — last-ditch fallback. Keeps items
   from landing image-less, but Webflow re-hosts with UUID basenames.
   Emits a loud `warning` mentioning both recovery paths:
   ```
   [Webflow] {listing_id}: ni Webflow Assets ni Cloudinary produjeron
   URLs hospedadas; usando URLs remotas de MilAnuncios (N imágenes).
   Configura CLOUDINARY_CLOUD_NAME/API_KEY/API_SECRET o regenera
   WEBFLOW_TOKEN con assets:read/assets:write — en caso contrario
   Webflow re-hospedará con nombres basados en hash en lugar de los
   slugs SEO.
   ```

The uploader returns `(image_urls, cloudinary_public_ids)`. The caller
in `webflow_sync.py` runs `cloudinary_client.delete_images(...)` in a
`finally` block after `create_item_draft` — success or failure — so the
Cloudinary free tier never accumulates stale staging files. On retry,
the next sync re-uploads with `overwrite=True`, so there is no benefit
to keeping a stale copy.

### Tracking column (`db.py`)

- New column: `webflow_assets_synced_at TIMESTAMP` (added via
  `_NEW_COLUMNS`, same auto-migration pattern as `webflow_slug`).
- New helper: `mark_webflow_assets_synced(conn, listing_id)` stamps
  `CURRENT_TIMESTAMP`. Used by Phase G to make re-runs idempotent.

## Migration (`scripts/migrate_images.py`)

Idempotent two-phase orchestrator with `--dry-run`, `--skip-webflow`,
`--quality`, `--max-dim`.

### Phase F — Compress + convert local images to WebP

Input: every row where `images_local IS NOT NULL AND images_local != 'null'`.

For each JSON-encoded path:

| Source state | Target state | Action |
|---|---|---|
| `.jpg`/`.png`/etc. exists | target `.webp` missing | `compress_to_webp()`, remove source, record new path |
| `.jpg`/`.png`/etc. exists | target `.webp` exists | Adopt target, remove source, record new path |
| `.webp` already exists | size ≤ 80 KB | Skip (already compressed) |
| `.webp` already exists | size > 80 KB | Recompress in place at configured quality |
| Source missing, target exists | — | Adopt target silently (prior run) |
| Source missing, target missing | — | Log warning, leave DB entry alone |

Per-row atomic commit: rewrite `images_local` JSON only after all paths
in the row have been processed. Progress log every 50 rows. Summary dict:
`{converted, recompressed, adopted, skipped, failed, rows_updated}`.

### Phase G — Re-upload images to Webflow Assets API

**Auth probe first:** `GET /sites/{id}/assets`. On 403 with
`missing_scopes`, abort cleanly with exit code 2 and a message telling
the user to regenerate `WEBFLOW_TOKEN` with `assets:read` /
`assets:write`. Prevents wasted time if the token is still wrong.

**Draft-only filter:** After the auth probe, paginate
`GET /collections/{id}/items` (limit=100) once and collect the IDs of
every item where `isDraft=true`. Only rows whose `webflow_item_id` is
in that set are processed — already-published items are logged as
`skipped_published` and left completely untouched. Rationale: the fix
must not disturb the live blog; it is applied silently in the
background and only reaches readers the next time an editor publishes
the affected item.

Input query:

```sql
SELECT listing_id, title, webflow_item_id, webflow_slug, images_local
FROM listings
WHERE webflow_item_id IS NOT NULL
  AND webflow_item_id != ''
  AND webflow_item_id != 'DUPLICATE'
  AND images_local IS NOT NULL
  AND images_local != 'null'
  AND webflow_assets_synced_at IS NULL
```

Per row:

0. If `webflow_item_id` is not in the draft-ID set → log as
   `skipped_published`, continue (never touch a live item).
1. Load up to 10 local `.webp` paths (matches the existing sync cap at
   `webflow_sync.py:195`).
2. For each path: `hosted_url = await client.upload_asset(path, path.name)`
   → collect, skip `None` results.
3. Empty result → log error, continue (row stays unmarked for retry).
4. Build partial `fieldData` with only the image fields that the
   collection actually exposes (reuse the availability check from
   `webflow_sync.build_field_data`):

   ```python
   alt = row["title"] or row["webflow_slug"]
   field_data = {
       "main-image":    {"url": hosted_urls[0], "alt": alt},
       "listing-images": [{"url": u, "alt": alt} for u in hosted_urls],
       "all-images":     [{"url": u, "alt": alt} for u in hosted_urls],
   }
   ```

5. `await client.update_items([{"id": webflow_item_id, "fieldData": field_data}])`
6. On success → `mark_webflow_assets_synced(conn, listing_id)`.
7. Sleep 0.6 s between items (matches existing sync cadence).

Progress log every 10 rows. Final summary:
`{uploaded, failed, skipped, skipped_published}`.

## Prerequisites

### Path A — regenerate the Webflow token (blocks Phase G)

1. Regenerate `WEBFLOW_TOKEN` in the Webflow dashboard with scopes:
   - `cms:read`, `cms:write`
   - `assets:read`, `assets:write` ← currently missing
   - `sites:read`
2. Add `WEBFLOW_SITE_ID=673373bb232280f5720b71e9` to `.env`.
3. Phases F and the rest of the pipeline do **not** need the new token.

### Path B — Cloudinary staging host (unblocks new listings only)

Used when Path A is not available (e.g. workspace owner can't rotate
the token). New listings synced from now on keep the slug-based CDN
filename; already-synced items with UUID basenames stay as-is.

1. Sign up for the Cloudinary free tier (25 GB storage, 25k monthly
   transformations — plenty since each asset is deleted seconds after
   Webflow copies it).
2. Dashboard → *Settings → API Keys*. Copy `Cloud name`, `API Key`,
   `API Secret`.
3. Add to `.env`:
   ```
   CLOUDINARY_CLOUD_NAME=
   CLOUDINARY_API_KEY=
   CLOUDINARY_API_SECRET=
   ```
4. Restart the FastAPI service so it picks up the new env vars.

## Risks

| Risk | Mitigation |
|---|---|
| Corrupted image bytes | `try/except` around `compress_to_webp`; log + skip, leave source untouched |
| Animated GIF / unsupported mode | Forced `convert("RGB")`; failure falls back to "skip" with warning |
| Phase F crash mid-listing | Per-row commit — at most one row inconsistent; re-run adopts existing `.webp` |
| Webflow rate limit (60 req/min) | 0.6 s sleep between uploads / items |
| Token still lacks scopes | Phase G auth probe aborts fast with exit code 2 |
| Collection lacks `listing-images` / `all-images` | Availability check skips missing fields |
| Webflow PATCH 404 (item deleted) | Log + clear `webflow_item_id` → next normal sync recreates it |
| `main-image` alt empty | Defaults to `webflow_slug` |
| WebP output larger than source | Rare for MilAnuncios JPEGs; accepted by the "re-encode all" decision |
| Breaking Webflow live image URLs | Explicitly in-scope — same decision as slug migration |

## Non-goals

- Re-fetching original-resolution images from MilAnuncios
- Deleting orphaned hash-named assets from Webflow's media library
- AVIF / responsive `srcset`
- `pillow-simd` for speed
- Dashboard UI changes
- Removing the remote-URL fallback path entirely — kept as loud degraded mode
- Test suite (codebase has none)
