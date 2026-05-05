# Codex code review — 2026-05-04

**Reviewer:** Codex (delegated via `superpowers` rescue agent)
**Scope:** Full backend codebase (Python). Frontend out of scope.
**Result:** 21 findings — 9 bugs, 6 performance bottlenecks, 6 refactors.

The three highest-leverage actions live at the bottom in **Executive Summary**.

---

## Bugs

### 1 [high] `DISPLAY` default in `launch_scraper` is `:1`, but Xvfb runs on `:99`

`api/scraper_job.py:272` sets `env.setdefault("DISPLAY", ":1")` as the
fallback when `DISPLAY` is not already in the environment. The VPS always
exports `DISPLAY=:99` from `run_api.sh:50`, so this is harmless when the API
is started via the shell script. However, if the API is launched directly
(e.g. from a systemd unit without `EnvironmentFile`, or from a pytest run),
the subprocess Chrome will try to connect to `:1`, which either does not
exist or belongs to a different X session. Chrome will fail to open with a
silent `Chrome exited with code 1` rather than a useful message.

**Fix:** change line 272 to `env.setdefault("DISPLAY", ":99")` to match the
Xvfb instance the project depends on.

### 2 [high] `PRAGMA busy_timeout` is never set — concurrent writers will fail with `OperationalError: database is locked` under load

`db.py:137-140`, `api/dependencies.py:34-36`, and `webflow_sync.py:281-283`
all open SQLite connections with WAL mode but no `busy_timeout`. In WAL mode
SQLite allows concurrent readers, but only one writer at a time. During a
live scrape session, three writers can be active simultaneously: the
scraper subprocess (via its own `init_db` connection), the FastAPI
process's `update_webflow_id` calls (via `webflow_sync.py` which opens its
own connection at line 281), and the scheduler if it fires. When the
scraper subprocess holds the write lock during `conn.commit()` after
`insert_listing`, any concurrent write from the API process will
immediately raise `OperationalError: database is locked` because the
default timeout is 5 ms.

**Fix:** add `conn.execute("PRAGMA busy_timeout=5000")` (5 seconds) in
`init_db`, in `get_db`, and in `sync_pending_listings`'s own
`sqlite3.connect`.

### 3 [high] `403 Forbidden` from Webflow Assets API is not visible — operator has no signal that uploads are silently falling through to Cloudinary

`webflow_client.py:163-164` intercepts HTTP 404 from the Assets API and
returns `None` gracefully. However, 403 (the documented error when the
token lacks `assets:read`/`assets:write`) is not caught — `r.raise_for_status()`
at line 164 will raise. The exception is caught upstream in
`webflow_image_uploader.py:94` with `except Exception as e: logger.debug(...)`.
So the fallback chain itself works. The real bug is that a misconfigured
token produces no visible warning in the dashboard log — the operator has
no signal that all uploads are falling through to Cloudinary.

**Fix:** change the `except` at `webflow_image_uploader.py:94` from
`logger.debug` to `logger.warning`, and add a specific 403 check in
`upload_asset` mirroring the 404 path.

### 4 [high] `parse_initial_props_json` fails silently on page-structure change — no downstream alert is raised

`parser.py:22-38`: when `window.__INITIAL_PROPS__` is absent
(Kasada/F5 block, A/B test, page redesign), the function returns `{}`. The
caller `parse_listing_page` at line 910 does `ad = props.get("ad", {})` and
continues with an empty dict, producing a row where `listing_id`, `title`,
`price_numeric`, `surface_m2`, and `ad_type` are all `None`. This row is
then INSERTed (`listing_id` is recovered from the URL via
`parse_listing_id`). The listing lands in the DB with correct ID but
almost all fields empty. There is no `logger.warning` at the point where
`props == {}` is detected.

**Fix:** add `if not props: logger.warning("[parser] __INITIAL_PROPS__ not found for %s — all fields will be empty", url)` after line 910 in
`parse_listing_page`. Also consider raising a `ScrapeBanException` when the
returned `ad` dict is empty and the HTML contains known ban markers.

### 5 [medium] Double invocation of `parse_title` and `parse_description` in `parse_listing_page`

`parser.py:933,956`: `parse_title(soup)` and `parse_description(soup, ad_json=ad)`
are each called twice — once to populate the return dict and once to supply
`title=` and `description=` arguments to `parse_ad_type`. Both calls
re-traverse the BeautifulSoup tree.

**Fix:** compute them once into local variables and reuse them.

### 6 [medium] `_scan_text_for_ad_type` price-per-m2 regex can produce false dual classifications

`parser.py:569`: the pattern `\b\d+(?:[.,]\d+)?\s*€?\s*/\s*m[²2]\b` matches
any `number/m²` string, including venta descriptions that quote price per
square meter ("Precio: 850 €/m²"). The dangerous case for the new dual
mode: a venta listing that describes comparative prices
("precio de venta: 900 €/m²; alquiler estimado: 6 €/m²") could score both
families ≥ 2 hits and be classified `venta_alquiler`. The URL hint provides
a safety net for URL-says-venta listings, but URL-ambiguous cases would
trigger dual without warning.

**Fix:** the dual-classification branch in `parse_ad_type` currently logs
at `INFO` (`parser.py:638-642`). Promote those to `WARNING` so the audit
log captures borderline classifications.

### 7 [medium] `google-place-id` URL stash — partial dedup-index corruption is not documented

`webflow_sync.py:63-66`: the documented temporary stash. The non-obvious
risk: the dedup index in `_build_source_url_index` (`webflow_sync.py:248`)
reads `field_data.get(source_slug)` where `source_slug` resolves to
`google-place-id`. If anyone manually sets a real Google Place ID in that
field before the migration to `source-url` happens, the dedup index will
treat that Place ID as a MilAnuncios URL and never match — so the dedup
check silently stops working for that item. This is not in the existing
decision doc.

**Fix:** add a guard in `_build_source_url_index` that skips index entries
whose value does not match `^https?://` (so non-URL Place IDs are filtered
out) and amend `docs/decisions/2026-05-04-source-url-temp-stash.md` to
note the risk.

### 8 [low] `_monitor_proc` re-imports `re` inside the hot line-reading loop

`api/scraper_job.py:189,194,204`: `import re` is repeated inside three
branches of the line-parsing loop. Python caches module imports so this is
not a correctness bug, but it adds a dict lookup per line.

**Fix:** move `import re` to the module top-level.

### 9 [low] `total_skipped` counter in the dashboard never updates in real time

`api/scraper_job.py:203-206`: the monitor parses `"Duplicados"` /
`"saltados"` (case-insensitive). The scraper's summary line is only
emitted at the end of a run. During the run, per-listing duplicate log
lines say `[SKIP] Ya existe: 123456789 (3/10 consecutivos)` — none of
which match. So `status["total_skipped"]` in the dashboard stays at 0
until the scrape finishes.

**Fix:** add a regex branch in `_monitor_proc` matching the in-flight
`[SKIP] Ya existe:` log line.

---

## Performance

### 1 [high] Image uploads are fully serial — 20 images per listing take ~80 s with the triple-fallback chain

`webflow_image_uploader.py:73-107`: uploads proceed in a `for` loop with
sequential `await client.upload_asset(...)` / `await cloudinary_upload(...)`.
There is no `asyncio.gather` or semaphore. At measured ~4 s per image with
the fallback, 20 images takes ~80 s per listing — dominant wall-clock
bottleneck for any listing with > 5 images.

**Fix:** gather uploads with a bounded semaphore (e.g. 5 concurrent) so
per-listing wall time drops from O(N) to roughly O(N/5). Webflow Assets
and Cloudinary are independent services with no ordering requirement.

### 2 [high] `_build_source_url_index` paginates the entire CMS collection on every sync run

`webflow_sync.py:227-258` calls `client.list_items()` which paginates at
100 items/page with a 0.6 s throttle (`webflow_client.py:265`). At 1228
items that is 13 pages × 0.6 s = ~7.8 s of pure sleep per run, plus 13
HTTP round-trips. This runs on every call to `sync_pending_listings`.
Once all legacy items have `webflow_item_id` set in the local DB, the
local `WHERE webflow_item_id IS NULL` query already excludes them, making
the Webflow-side index redundant for the common case.

**Fix:** skip `_build_source_url_index` when `get_unsynced_listings`
returns 0 rows (cheap pre-check). Optionally persist the index between
runs in a lightweight local JSON cache keyed by collection schema version.

### 3 [medium] Browser warm-up (~30 s) runs on every browser rotation

`milanuncios.py:177` calls `await warmup(browser)` from inside
`_start_browser()`. `_start_browser()` is called every
`_BROWSER_REFRESH_EVERY = 10` requests. So the full 3-step warm-up
(homepage + category + captcha wait) runs after every 10 listings, adding
1-3 s/listing amortised overhead for what should be only a token refresh.

**Fix:** parametrise warm-up — full 3-step on first launch, lighter
single-page reload on rotations.

### 4 [medium] Browser persistence is correct but the rotation reset is worth documenting

`milanuncios.py:83-90`: rotation fires when `requests_count % 10 == 0`
AND `requests_count > 0`. After `_close_browser_internal()`,
`_session["requests_count"]` is reset to 0. The next call sees
`browser is None`, calls `_start_browser()`, count starts fresh. This is
correct — the browser stays alive across all listings within a 10-request
window and `page = await browser.get(url)` reuses the existing instance.
No bug, but worth a comment.

### 5 [medium] Cloudinary `urllib3` connection-pool warnings — caused by parallel `delete_images` with no pool size tuning

`cloudinary_client.py:182-186`: `delete_images` gathers all deletions
concurrently with `asyncio.gather`. Each runs in a thread via
`asyncio.to_thread`. Underlying `cloudinary.uploader.destroy` uses
`requests` (urllib3). With ~20 concurrent deletes, urllib3's default pool
size of 10 spills into the "Connection pool is full" warnings observed in
sync runs.

**Fix:** either serialize deletes (the destroy step runs after item
creation, off the critical path) or pass a larger `max_connections` to
the Cloudinary config.

### 6 [low] `get_unsynced_listings` fetches all unsynced rows in one shot

`db.py:327-342`: no `LIMIT`. At scale (1000+ unsynced listings) this
materializes the full result set. The `idx_webflow_item_id` index makes
the `WHERE webflow_item_id IS NULL` filter efficient. The concern is RSS
during migration runs.

**Fix:** add `LIMIT/OFFSET` paging if a large back-fill is on the table.

---

## Refactors

### 1 [high] `integrations/parser.py` is 986 lines — more than 3× the project's 300-line cap

Natural split boundaries:

| Lines | New module | Contents |
|---|---|---|
| 1-50 | `parser_core.py` | `parse_initial_props_json`, `_get_attribute_value` |
| 51-530 | `parser_fields.py` | All individual field parsers (`parse_listing_id`, `parse_title`, `parse_price_numeric`, etc.) |
| 531-700 | `parser_ad_type.py` | `parse_ad_type` + keyword regex tables (4-layer cascade) |
| 701-986 | `parser_listing.py` | `parse_property_type`, `parse_photos`, `parse_listing_page` (orchestrator) |

`parse_listing_page` becomes a thin orchestrator. No behaviour change.

### 2 [medium] `integrations/webflow_sync.py` is 378 lines and `build_field_data` does four conceptually distinct jobs

`webflow_sync.py:100-222`: `build_field_data` handles (a) generic field-type
coercion loop, (b) mandatory `name`/`slug` injection, (c) price display
routing per ad_type, and (d) image splitting across four Webflow fields.

**Fix:** extract `_route_price_to_field(...)` and
`_assign_image_fields(...)` as private helpers; `build_field_data` becomes
a 20-line orchestrator. Also makes price routing testable in isolation.

### 3 [medium] `db.py` is 428 lines — schema + init + CRUD intertwined

| Lines | New module |
|---|---|
| 1-70 | `db_schema.py` (SCHEMA + index DDL) |
| 71-145 | `db_init.py` (init, migrate helpers) |
| 146-428 | `db.py` (CRUD only — ~285 lines, under cap) |

All existing `from db import ...` callers continue to work via re-exports.

### 4 [medium] `scripts/migrate_existing_listings.py` (330 lines) duplicates the canonical-title pipeline that lives in `scraper_engine.py`

`migrate_existing_listings.py:101-156` (`recompute_row`) re-implements the
same `parse_ad_type → build_canonical_title → generate_unique_slug`
pipeline that `scraper_engine.py:220-235` runs during live scraping. If
the canonical-title logic is updated in one, the other must be updated
manually.

**Fix:** extract a shared `compute_listing_metadata(row, conn) -> dict`
helper in `utils/listing_metadata.py`; both call sites import it.

### 5 [medium] Five orphan test files at repo root should be deleted

`test_api.py`, `test_api2.py`, `test_error.py`, `test_launch.py`,
`test_tabs.py` — all at the repo root. Ad-hoc debug scripts:
- one runs live HTTP against localhost
- one fabricates an `httpx.HTTPStatusError`
- one imports `nodriver` (the pre-fork package name) and will fail on
  import in the current env

Not collected by pytest (which targets `tests/`). They confuse the
"what's the test surface" question.

**Fix:** `git rm` all five.

### 6 [low] `FIELD_MAP_PATTERNS` candidate mechanism silently drops a field on schema rename

`webflow_sync.py:82-96`: unmatched fields are logged at `INFO`. In a
production sync run, an INFO line about dropped fields is easy to miss.
Two specific risks: (a) if `new-sale-price` is renamed to `sale-price`,
the price field sends no value with only an INFO log; (b) once Benedict
adds `source-url`, the candidate list correctly prefers it over the
`google-place-id` stash — that part is safe.

**Fix:** promote the unmatched-fields log from `INFO` to `WARNING` at
`webflow_sync.py:95`.

---

## Executive summary — top 3 highest-leverage actions

1. **Add `PRAGMA busy_timeout=5000` to every SQLite connection open.**
   Three concurrent writers (scraper subprocess, `sync_pending_listings`,
   FastAPI request handler) can race during a live scrape-and-sync
   session. Without a busy timeout the default 5 ms window means any
   write collision raises `OperationalError`. This is a data-loss path on
   the hot code. One-line fix in three call sites.

2. **Parallelize image uploads with `asyncio.Semaphore(5)`.** The current
   serial loop in `webflow_image_uploader.py` is the dominant wall-clock
   bottleneck for any listing with more than 5 images. A 20-image listing
   takes ~80 s before the Webflow item is even created. `gather` with a
   semaphore reduces that to ~20 s with no API contract changes.

3. **Split `integrations/parser.py` (986 lines) into four focused
   modules.** At nearly 4× the project's 300-line cap, this file is the
   single largest maintainability debt item. The proposed split (core /
   fields / ad_type / listing) requires zero behaviour changes and brings
   all four files under cap.
