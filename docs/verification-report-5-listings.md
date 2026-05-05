# 5-Listing Verification — Iteración 2026-05

**Date:** 2026-05-04
**Corpus:** 5 freshly scraped MilAnuncios industrial-warehouse listings,
synced through the production scrape → sync path into the live Webflow CMS
(collection "Spain Warehouses", `673373bb232280f5720b72ca`).

**Coordinate sanity:** every lat/lng round-tripped through OpenStreetMap
Nominatim reverse-geocoding to confirm it resolves to the same
city/province MilAnuncios claims.

**Result:** 5/5 pass on all 9 Benedict tasks. 5/5 coordinates resolve to
the correct province.

---

## Test corpus (live drafts in CMS)

| listing_id | ad_type | Webflow item id | Location | Source URL |
|---|---|---|---|---|
| 593740926 | alquiler | `69f9397e273cd3be7bf2bff1` | Barberà del Vallès (Barcelona) | [link](https://www.milanuncios.com/alquiler-de-naves-industriales-en-barbera-del-valles-barcelona/barbera-del-valles-593740926.htm) |
| 593718237 | alquiler | `69f93973db0adfc552ead44c` | Albuixech (Valencia) | [link](https://www.milanuncios.com/alquiler-de-naves-industriales-en-albuixech-valencia/albuixech-593718237.htm) |
| 593703965 | venta | `69f93963db1871da5455c564` | Era Alta (Murcia) | [link](https://www.milanuncios.com/venta-de-naves-industriales-en-era-alta-murcia/murcia-capital-593703965.htm) |
| 593703895 | venta | `69f93957460172a1dfe867c7` | Murcia (Murcia) | [link](https://www.milanuncios.com/venta-de-naves-industriales-en-murcia-murcia/murcia-capital-593703895.htm) |
| 593703284 | alquiler | `69f9393f6db66eae8bec827c` | Montcada i Reixac (Barcelona) | [link](https://www.milanuncios.com/alquiler-de-naves-industriales-en-montcada-i-reixac-barcelona/montcada-i-reixac-593703284.htm) |

CMS link: https://webflow.com/dashboard/sites/673373bb232280f5720b71e9/cms

---

## Per-task pass matrix

Every cell is "OK" — the table is shown so the failure surface is
visible at a glance.

| listing_id | T1 ad_type | T2 title | T2 slug | T3 images | T4 RichText | T5 price | T7 src URL | T8 contact | T9 lat/lng | Coord OK |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| 593740926 | OK | OK | OK | OK | OK | OK | OK | OK | OK | OK |
| 593718237 | OK | OK | OK | OK | OK | OK | OK | OK | OK | OK |
| 593703965 | OK | OK | OK | OK | OK | OK | OK | OK | OK | OK |
| 593703895 | OK | OK | OK | OK | OK | OK | OK | OK | OK | OK |
| 593703284 | OK | OK | OK | OK | OK | OK | OK | OK | OK | OK |

T6 (Webflow-side dedup index) is verified once per sync run — the
index reported `1228 items fetched, dedup keys built` during this
sync, identical behaviour as previous runs.

---

## Per-listing details

### 1 — `593740926` — Barberà del Vallès (alquiler)

| | |
|---|---|
| Webflow name | `Nave industrial en alquiler en Barbera del Valles (Barcelona)` |
| Webflow slug | `nave-industrial-en-alquiler-en-barbera-del-valles-barcelona` |
| Description | starts `<p>Nave industrial en alquiler en Can Salvatella (Barberà de…` |
| Sale price / Rent | — / `5.44€/m²` |
| Contact | `ENGEL & VÖLKERS` / `935154444` |
| Source URL stash | on `google-place-id` |
| Images | scraped 9 → main 1 / top4 4 / all5 5 / additional 4 |
| lat / lng | `41.513703 / 2.1494579` |
| Reverse-geocode | "Barberà del Vallès, Vallés Occidental, **Barcelona**, Cataluña, 08210, España" → ✅ matches |

### 2 — `593718237` — Albuixech (alquiler)

| | |
|---|---|
| Webflow name | `Nave industrial en alquiler en Albuixech (Valencia)` |
| Webflow slug | `nave-industrial-en-alquiler-en-albuixech-valencia` |
| Description | starts `<p>Se ofrece en alquiler unalmacen situado en Albuixech…` |
| Sale price / Rent | — / `3.33€/m²` |
| Contact | `INMOBILIARIA PALANCA FONTESTAD` / `961490135` |
| Source URL stash | on `google-place-id` |
| Images | scraped 12 → main 1 / top4 4 / all5 5 / additional 7 |
| lat / lng | `39.5465416 / -0.3232981` |
| Reverse-geocode | "Albuixech, L'Horta Nord, **Valencia**, Comunidad Valenciana, 46550, España" → ✅ matches |

### 3 — `593703965` — Era Alta (venta)

| | |
|---|---|
| Webflow name | `Nave industrial en venta en Era Alta (Murcia)` |
| Webflow slug | `nave-industrial-en-venta-en-era-alta-murcia` |
| Description | starts `<p>Nave-Almacén en Alquiler - 102 m2 en Era Alta (Murcia) Id…` |
| Sale price / Rent | `55.000 €` / — |
| Contact | `ALQUILOTUCASA VENDOTUCASA MURCIA BENIAJÁN` / `654803685` |
| Source URL stash | on `google-place-id` |
| Images | scraped 8 → main 1 / top4 4 / all5 5 / additional 3 |
| lat / lng | `37.972831903 / -1.153625471` |
| Reverse-geocode | "Murcia, Área Metropolitana de Murcia, **Región de Murcia**, España" → ✅ matches |

> **Note for Benedict.** The description here begins "Nave-Almacén en
> Alquiler" even though the URL and price (55 000 €) are venta. The 4-layer
> classifier kept "venta" because (a) the URL says venta, (b) the
> description has only one `alquiler` mention, below the `_DUAL_MIN_HITS = 2`
> threshold needed to override the URL or trigger dual mode. This is the
> intended conservative behaviour — sporadic mentions don't flip the
> classification. If listings like this ever need finer attention, the
> `audit_ad_types.py` script flags them.

### 4 — `593703895` — Murcia (venta)

| | |
|---|---|
| Webflow name | `Nave industrial en venta en Murcia (Murcia)` |
| Webflow slug | `nave-industrial-en-venta-en-murcia-murcia` |
| Description | starts `<p>Se vende parcela en Senda De los Garres, parcela de 2.86…` |
| Sale price / Rent | `399.000 €` / — |
| Contact | `ALQUILOTUCASA VENDOTUCASA MURCIA BENIAJÁN` / `654803685` |
| Source URL stash | on `google-place-id` |
| Images | scraped 50 → main 1 / top4 4 / all5 5 / additional 15 (cap 20 hit) |
| lat / lng | `37.97015336500099 / -1.1088618811697395` |
| Reverse-geocode | "Murcia, Área Metropolitana de Murcia, **Región de Murcia**, España" → ✅ matches |

### 5 — `593703284` — Montcada i Reixac (alquiler)

| | |
|---|---|
| Webflow name | `Nave industrial en alquiler en Montcada I Reixac (Barcelona)` |
| Webflow slug | `nave-industrial-en-alquiler-en-montcada-i-reixac-barcelona` |
| Description | starts `<p>PB 438 m2 + Altillo 193 m2 + Patio 180 m2</p><p>Estructur…` |
| Sale price / Rent | — / `7.00€/m²` |
| Contact | `Nolkers Consulting` / `670501198` |
| Source URL stash | on `google-place-id` |
| Images | scraped 15 → main 1 / top4 4 / all5 5 / additional 10 |
| lat / lng | `41.48527370000001 / 2.1611658` |
| Reverse-geocode | "Montcada i Reixac, Vallés Occidental, **Barcelona**, Cataluña, España" → ✅ matches |

---

## Coordinate verification methodology

For every listing:

1. The scraper extracts `latitude` / `longitude` from the
   `window.__INITIAL_PROPS__` JSON of the listing page —
   `ad.location.geolocation.latitude/longitude` (`integrations/parser.py::parse_coordinates`).
2. The values are persisted to the SQLite columns `latitude REAL`,
   `longitude REAL` and shipped as `PlainText` to the Webflow slugs
   `latitude` / `longitude`.
3. **Verification step:** the same lat/lng pair was sent to OpenStreetMap
   Nominatim (`reverse?lat=…&lon=…`, rate-limited at 1.2 s between
   requests). The returned `state` / `county` / `display_name` was
   matched against the listing's claimed `province` and `location`.

All 5 lat/lng pairs resolve to the correct province on the first try.
None of them point to filler (0.0,0.0) or any out-of-Spain region.

---

## How to reproduce

```bash
# fresh DB
rm -f /tmp/test_real.db /tmp/test_real.db-shm /tmp/test_real.db-wal

# scrape 5 listings (uses headful Chrome on DISPLAY=:1 — Linux)
DB_PATH=/tmp/test_real.db DISPLAY=:1 \
  python3 scraper_engine.py --pages 2 --batch 5

# push to Webflow
DB_PATH=/tmp/test_real.db python3 -c "
import asyncio
from integrations.webflow_sync import sync_pending_listings
print(asyncio.run(sync_pending_listings()))
"

# rerun the verification (this report's script lives in /tmp/verify.py
# during the chat session; saving it as a permanent script is on the
# back-burner until we decide whether to wire it into CI).
```

---

## What this report does NOT prove

1. **Long-term Webflow stability.** A draft was created and read back
   in the same minute. A run held overnight could surface API quirks
   (rate limiting under load, schema drift, etc.) — out of scope for
   this verification.
2. **Image quality.** The image-uploader was confirmed end-to-end
   (Cloudinary → Webflow CDN), but no visual diff is performed against
   the source thumbnails.
3. **Phase-2 geocoding fallback.** All 5 listings happened to have
   coordinates in the source JSON. Listings without `geolocation` will
   still ship empty `latitude` / `longitude` until Phase 2 (Nominatim
   or Google Maps) is wired in.

---

## Reference

- Per-task implementation report: `docs/verification-report-2026-05-final.md`
- Iteration changelog: `docs/iteration-2026-05-feedback.md`
- Webflow schema snapshot: `docs/webflow-schema.json`
- Decision doc — temp `google-place-id` stash for Task 7:
  `docs/decisions/2026-05-04-source-url-temp-stash.md`
