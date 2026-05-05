# Verification Report — 9 Benedict tasks (Iteración 2026-05)

**Date:** 2026-05-04
**Scope:** End-to-end verification of every task in Benedict's feedback against
real MilAnuncios listings synced into the live Webflow CMS.
**Test corpus:** 3 freshly scraped listings, one per ad-type variant.

| # | Listing | listing_id | ad_type | Webflow item id |
|---|---|---|---|---|
| A | Don Benito (Badajoz) — dual offering | 567490293 | `venta_alquiler` | `69f8ef5ea57cc4ed3aa02ffe` |
| B | Esparreguera (Barcelona) — sale | 592996766 | `venta` | `69f9259970273eeb84b8285b` |
| C | Mollet del Vallès (Barcelona) — rent | 589388620 | `alquiler` | `69f925823190dc447cc15866` |

All three were created through the production scrape → sync path
(`scraper_engine.py --pages 1 --batch N` then `sync_pending_listings`).
Drafts remain in the CMS for inspection.

**Test suite:** 225 unit + integration tests passing (`python3 -m pytest tests/ -q`).

---

## Status by task

| # | Task | Status | Notes |
|---|---|---|---|
| 1 | Detect venta / alquiler / **dual** | ✅ **Improved** | Cascade now also returns `venta_alquiler` |
| 2 | Canonical title + slug | ✅ Verified | Dual phrase included |
| 3 | Image dedup + 4-way split | ✅ Verified | Cap 20 honoured |
| 4 | Description as RichText | ✅ **Improved** | Now also strips `Ref: <code>.` prefix |
| 5 | Price formatting | ✅ Verified | Dual reuses alquiler routing |
| 6 | Webflow-side dedup | ✅ **Active** | Index built from `google-place-id` stash; 23 items already indexed |
| 7 | Source URL in CMS | ✅ **Unblocked (temporary)** | Parked in `google-place-id` until Benedict creates `source-url` |
| 8 | Contact data | ✅ **Unblocked** | `contact-name` + `contact-number` Benedict added are now populated |
| 9 | Geocoding | ✅ Phase 1 | Phase 2 (Nominatim/Google fallback) still pending |

Net change vs. previous handoff: tasks 7 and 8 moved from blocked
(🚫) to live (✅), and tasks 1 and 4 picked up additional behaviour
the client requested today (dual detection + Ref-prefix stripping).

---

## Task 1 — Detect venta / alquiler / dual

**Requirement.** Classify every listing as a sale or a rental. Recover from
mis-categorised source data. New today: when a listing offers **both**
modalities (e.g. "Consulte precio de VENTA o ALQUILER"), surface it as
`venta_alquiler`.

**Implementation.** `integrations/parser.py::parse_ad_type` runs a
4-layer cascade and returns a 3-valued result:

1. JSON `categories[].slug/name`
2. JSON `sellType` (`supply` → venta, `demand` → alquiler)
3. URL keyword (`/venta-de-naves/`, `/alquiler-de-naves/`)
4. Keyword scan over title + description; **`venta_alquiler`** is
   returned when both keyword families register ≥ 2 hits each
   (`_DUAL_MIN_HITS`). The dual case overrides a single URL hint.

**Live verification.**

| Listing | DB `ad_type` | Expected | OK |
|---|---|---|---|
| Don Benito | `venta_alquiler` | `venta_alquiler` (URL says alquiler, body offers both) | ✅ |
| Esparreguera | `venta` | `venta` (URL says venta, body single-modal) | ✅ |
| Mollet | `alquiler` | `alquiler` | ✅ |

**Tests.** `tests/test_parser.py::TestParseAdType` — 16 cases, including
the 4 new dual-detection cases.

**Audit script.** `scripts/audit_ad_types.py` re-applies the cascade to
existing rows and reports `flip` / `fill_null` / `noop` decisions.

---

## Task 2 — Canonical title + slug

**Requirement.** Replace the raw MilAnuncios titles with the format
`Nave industrial en {tipo} en {Name}` and use the same string as the
Webflow page slug.

**Implementation.** `utils/slugify.py`:

- `extract_warehouse_name(data)` resolves `{Name}` (location → address
  with street keyword fallback).
- `build_canonical_title(ad_type, name)` produces the title via a phrase
  map: `venta` → "venta", `alquiler` → "alquiler",
  **`venta_alquiler` → "venta o alquiler"**.
- `slugify_title` + `generate_unique_slug` for collision-safe slugs.

`scraper_engine.run()` applies it at scrape time; pre-existing rows are
covered by `scripts/migrate_canonical_titles.py` (which also emits the
`reports/redirects_*.csv` file Benedict needs to load in Webflow Site
Settings → Hosting → Redirects before publishing).

**Live verification.**

| Listing | Title in Webflow | Slug |
|---|---|---|
| Don Benito | `Nave industrial en venta o alquiler en Don Benito (Badajoz)` | `nave-industrial-en-venta-o-alquiler-en-don-benito-badajoz` |
| Esparreguera | `Nave industrial en venta en Esparreguera/Esparraguera (Barcelona)` | `nave-industrial-en-venta-en-esparreguera-esparraguera-barcelona` |
| Mollet | `Nave industrial en alquiler en Mollet del Valles (Barcelona)` | `nave-industrial-en-alquiler-en-mollet-del-valles-barcelona` |

**Tests.** `tests/test_slugify.py::TestBuildCanonicalTitle` and
`TestExtractWarehouseName` — 12 cases including the new dual phrase.

---

## Task 3 — Image dedup + 4-way split

**Requirement.** Single source of truth for images, deduplicated and
split into the four CMS slots:

| Webflow slug | Label | Content |
|---|---|---|
| `main-image` | Main Image | image 1 |
| `listing-images` | Top 4 Best Images | images 2-5 |
| `all-images` | Airbnb Top 5 Images | images 1-5 |
| `additional-images` | Additional Images | images 6+ (capped at 20 total) |

**Implementation.** `integrations/webflow_sync.py::build_field_data`
deduplicates while preserving order, then assigns slices to each slug.
Image upload chain: Webflow Assets API → Cloudinary stage →
Webflow re-host (`integrations/webflow_image_uploader.py`).

**Live verification.**

| Listing | scraped | main | top4 | all-5 | additional | total uploaded |
|---|---|---|---|---|---|---|
| Don Benito | 10 | 1 | 4 | 5 | 5 | 10 |
| Esparreguera | 65 | 1 | 4 | 5 | 15 | **20 (cap)** |
| Mollet | 16 | 1 | 4 | 5 | 11 | 16 |

All slot counts match the spec; the 20-image cap kicks in correctly on
the 65-image Esparreguera listing.

**Tests.** `tests/test_webflow_sync.py::TestImageSplitting` — 9 cases.

---

## Task 4 — Description as RichText (+ Ref-prefix strip)

**Requirement.** Convert raw description text to HTML so Webflow's
RichText field renders paragraphs and bullet lists. New today: strip the
`Ref: <code>.` prefix that MilAnuncios prepends to most ads — it has no
value to the CMS reader.

**Implementation.** `utils/description_formatter.py`:

- `strip_ref_prefix(text)` removes a leading `Ref: 652-2936.` /
  `Referencia 12345 —` / similar pattern. Anchored to start so a "Ref:"
  later in the body is preserved.
- `format_description_html(raw)`:
  1. normalise line endings,
  2. apply `strip_ref_prefix`,
  3. split on blank lines → `<p>` per paragraph,
  4. detect `≥ 2` `•` markers in a paragraph → `<ul><li>` list,
  5. preserve single newlines as `<br>`,
  6. HTML-escape everything to prevent injection.

**Live verification (description body, first 60 chars).**

| Listing | Webflow description starts with |
|---|---|
| Don Benito (raw begins `Ref: 109832692-JM-041. Ponemos…`) | `<p>Ponemos a su disposición una céntrica nave con 902…` |
| Esparreguera | `<p>Nave industrial ( SOLAR AGRARIO RUSTICO) en ctra abrera m…` |
| Mollet | `<p>Posibilidad de compra a 500.000.-€</p><p>Nave industrial…` |

The Don Benito case proves the Ref-prefix strip works end-to-end (the
raw body in DB starts with `Ref: 109832692-JM-041. Ponemos…`).

**Tests.** `tests/test_description_formatter.py` — 23 cases including
8 new ones for the Ref-prefix strip.

---

## Task 5 — Price formatting

**Requirement.** Per ad-type display strings:

- venta → `199.000 €` (Spanish thousands separator)
- alquiler with €/m² → `1.19€/m²`
- alquiler fallback → `1.500 €/mes`

Today's addition: `venta_alquiler` reuses the alquiler routing (the
MilAnuncios price for these dual listings is the rental rate).

**Implementation.** `utils/price_formatter.py::format_price_display`
single source of truth. `integrations/webflow_sync.py` routes:

| ad_type | Field filled | Other field |
|---|---|---|
| `venta` | `new-sale-price` | `new-price-sm2-month` cleared |
| `alquiler` | `new-price-sm2-month` | `new-sale-price` cleared |
| `venta_alquiler` | `new-price-sm2-month` (per-m² primary) | `new-sale-price` cleared |

**Live verification.**

| Listing | new-sale-price | new-price-sm2-month |
|---|---|---|
| Don Benito (dual, price_per_m2=1.66) | None | `1.66€/m²` |
| Esparreguera (venta, price_numeric=650 000) | `650.000 €` | None |
| Mollet (alquiler, price_per_m2=5.55) | None | `5.55€/m²` |

**Tests.** `tests/test_price_formatter.py` — 18 cases (incl. dual);
`tests/test_webflow_sync.py::TestPriceFormattingByAdType` — 5 cases.

---

## Task 6 — Webflow-side de-duplication

**Requirement.** Before creating a CMS item for a freshly scraped
listing, check whether Webflow already holds an item with the same
source URL. If yes, adopt its id and skip re-creation.

**Implementation.** `integrations/webflow_sync.py::_build_source_url_index`
paginates `WebflowClient.list_items` (60 req/min throttle) and builds a
`{source_url: item_id}` map keyed off whichever slug
`FIELD_MAP_PATTERNS["url"]` resolves to. Right now that's
`google-place-id` (temp stash for Task 7). When Benedict adds the
dedicated `source-url` slug, the index keys silently switch.

**Live verification.** During the 2026-05-04 sync, the dedup index
reported:

```
[Webflow] list_items: fetched 1223 items
[Webflow] Dedup index built: 23 items with source-url
```

The 23 items are existing CMS items whose `google-place-id` field
already holds a MilAnuncios URL from earlier syncs. The dedup is
**active in production** — re-syncing a row that's already in CMS
short-circuits creation.

**Tests.** `tests/test_webflow_sync.py::TestBuildSourceUrlIndex` — 3 cases.

**Caveat.** When Benedict creates the real `source-url` slug, run a
one-shot back-fill to copy URLs from `google-place-id` → `source-url`
and clear `google-place-id` so the slot is free for actual Place IDs.
See `docs/decisions/2026-05-04-source-url-temp-stash.md` § "Reversal".

---

## Task 7 — Source URL in CMS (temporary stash)

**Requirement.** The original MilAnuncios listing URL must round-trip
through Webflow so editors can navigate back, and so dedup (Task 6)
has a stable key.

**Status before today.** Blocked — Webflow had no field. The 9-task
handoff listed this as 🚫.

**Status today.** ✅ **Unblocked via temporary stash.** The MilAnuncios
URL is written to the existing `google-place-id` slug. We chose this
slot because (a) it's the same `PlainText` type the eventual
`source-url` field will be, and (b) we don't yet collect Google Place
IDs anywhere in the pipeline, so the slot is unused. The decision plus
exact reversal steps are documented in
`docs/decisions/2026-05-04-source-url-temp-stash.md`.

**Implementation.** `FIELD_MAP_PATTERNS["url"]` candidate list:

```python
"url": ["source-url", "google-place-id", "url", "link", ...]
```

The first slug present in the live schema wins. The day Benedict adds
`source-url`, the next sync silently switches over with zero code
change.

**Live verification.**

| Listing | google-place-id |
|---|---|
| Don Benito | `https://www.milanuncios.com/alquiler-de-naves-industriales-en-don-benito-badajoz/...` |
| Esparreguera | `https://www.milanuncios.com/venta-de-naves-industriales-en-esparreguera...` |
| Mollet | `https://www.milanuncios.com/alquiler-de-naves-industriales-en-mollet-del-valles-...` |

**Tests.** `tests/test_webflow_sync.py::TestSourceUrlTempStashOnGooglePlaceId`
— 3 cases.

**Action for Benedict.** Create `Source URL` (slug `source-url`,
PlainText). When it lands, run the back-fill described in the decision
doc and remove `"google-place-id"` from the candidate list.

---

## Task 8 — Contact data (Llamar)

**Requirement.** Extract the seller's name and phone number from each
listing and surface them in the CMS.

**Status before today.** Blocked — Webflow had no `phone` field. The
9-task handoff listed this as 🚫.

**Status today.** ✅ **Unblocked.** Benedict has now added
`Contact Name` (`contact-name`) and `Contact Number` (`contact-number`)
to the collection. We also map both — `seller_name` → `contact-name`,
`phone` → `contact-number`.

**Implementation.** `FIELD_MAP_PATTERNS` extended with the two new
candidate lists in `integrations/webflow_sync.py`. Phone 2 is currently
skipped because there is no `phone-2` slug yet (already in the
candidate list, will activate the moment Benedict adds it).

**Live verification.**

| Listing | contact-name | contact-number |
|---|---|---|
| Don Benito | `Viare Home` | `607475393` |
| Esparreguera | `FINQUES ISAVI` | `937777070` |
| Mollet | `Nausmar Industrial Buildings` | `610309098` |

**Tests.** `tests/test_webflow_sync.py::TestContactFieldsMapping` — 3 cases.

---

## Task 9 — Geocoding (Phase 1)

**Requirement.** Latitude / longitude reach Webflow on every listing
that has them in the source.

**Implementation.**

1. `integrations/parser.py::parse_coordinates(ad_json)` reads
   `ad.location.geolocation.latitude / longitude` from the
   `window.__INITIAL_PROPS__` JSON every MilAnuncios listing page
   serves.
2. `db.py` persists them as `latitude REAL` / `longitude REAL` columns
   (auto-migrated via `_NEW_COLUMNS`).
3. `integrations/webflow_sync.py` ships them as `PlainText` to the
   `latitude` / `longitude` slugs.

**Live verification.**

| Listing | latitude | longitude | Source |
|---|---|---|---|
| Don Benito | `38.9572` | `-5.85842` | MilAnuncios `__INITIAL_PROPS__` |
| Esparreguera | `41.53037` | `1.90519` | MilAnuncios `__INITIAL_PROPS__` |
| Mollet | `41.5299113` | `2.2152869` | MilAnuncios `__INITIAL_PROPS__` |

All three listings shipped lat/lng directly from the source — no
geocoding API calls were made.

**Tests.** `tests/test_parser.py::TestParseCoordinates` — 4 cases;
`tests/test_db.py::TestCoordinates` — 4 cases;
`tests/test_webflow_sync.py::TestLatitudeLongitudeMapping` — 4 cases.

**Phase 2 (pending).** Some MilAnuncios listings publish without
coordinates. The fallback chain (Nominatim or Google Maps) is
designed but not implemented; needs Benedict's input on the precision
threshold.

---

## How to reproduce this verification

```bash
# 1. unit/integration suite
python3 -m pytest tests/ -q
# → 225 passed

# 2. fresh real-data scrape (clean DB, 3 listings)
rm -f /tmp/test_real.db /tmp/test_real.db-shm /tmp/test_real.db-wal
DB_PATH=/tmp/test_real.db DISPLAY=:1 \
  python3 scraper_engine.py --pages 1 --batch 3

# 3. push them to Webflow
DB_PATH=/tmp/test_real.db python3 -c "
import asyncio
from integrations.webflow_sync import sync_pending_listings
print(asyncio.run(sync_pending_listings()))
"

# 4. inspect each draft in the CMS
# https://webflow.com/dashboard/sites/673373bb232280f5720b71e9/cms
#   → Spain Warehouses → search 'venta' / 'alquiler' / 'venta o alquiler'
```

---

## Open items for Benedict

1. Create the `Source URL` (`source-url`, PlainText) slug in
   "Spain Warehouses" so Task 7 can move out of the temporary stash.
2. Decide on the geocoding fallback for Task 9 Phase 2
   (Nominatim vs Google Maps; cost vs precision).
3. Confirm the 20-image cap is acceptable (Esparreguera had 65; we
   shipped 20). Raising it is a one-line change in
   `MAX_IMAGES_PER_LISTING`.
4. Optional: create a `Phone 2` slug (`phone-2`) if a second contact
   number is sometimes useful — the candidate list is already wired.

---

## Reference

- Decision doc: `docs/decisions/2026-05-04-source-url-temp-stash.md`
- Iteration changelog: `docs/iteration-2026-05-feedback.md`
- Webflow schema snapshot: `docs/webflow-schema.json`
- Activation playbook: `docs/post-benedict-checklist.md`
