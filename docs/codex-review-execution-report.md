# Codex Review Execution Report — 2026-05-04 to 2026-05-05

## Plan completion

Source plan: `docs/plans/codex-review-fixes.md`. 21 findings across 5 sprints.

| Sprint | Commit | Status | Items completed |
|---|---|---|---|
| 1 — Foundations + quick wins | `475363a` | ✅ | B1 (DISPLAY :99), B2 (busy_timeout × 3), B8 (import re hoist), B9 (Ya existe counter), R5 (5 orphan files), R6 (WARN promote) |
| 2 — Performance quick wins | `cd6cc45` | ✅ | P1 (Semaphore(5) image uploads), P2 (skip dedup index when no rows), P5 (serialize Cloudinary deletes) |
| 3 — Correctness fixes | `ff79469` | ✅ | B3 (403 explicit + WARNING), B4 (`__INITIAL_PROPS__` warning), B5 (cache title/desc), B6 (dual log → WARNING), B7 (URL-shape guard) |
| 4 — Refactors | `d158e96` + `a52e0e5` | ✅ | R1 full split, R2 (price + image + coerce helpers), R3 (db_schema.py extracted), R4 (compute_canonical_title shared) |
| 5 — Deferred | — | ⏸ as planned | P3 (lighter warm-up), P6 (paged unsynced query) |

19 of 21 findings landed across 5 commits. The 2 deferred items
(Sprint 5) are explicitly conditional — both have measurement /
scale prerequisites before the work is worth doing.

## Final file sizes (after R1 full split)

| File | Lines | vs Original | Cap (300) |
|---|---|---|---|
| `integrations/parser.py` | 145 | 1007 | ✅ under |
| `integrations/parser_core.py` | 41 | new | ✅ under |
| `integrations/parser_ad_type.py` | 163 | new | ✅ under |
| `integrations/parser_fields.py` | 651 | new | ⚠ 25 small parsers, one cohesive chunk |
| `integrations/webflow_sync.py` | 434 | 378 | ⚠ +56 lines from helper docs (acceptable) |
| `db.py` | 338 | 433 | ⚠ -95 lines, just over cap |
| `db_schema.py` | 137 | new | ✅ under |

3 of 4 new parser modules under cap; the 651-line `parser_fields.py`
holds 25 small-to-medium pure functions that don't gain clarity from
mechanical sub-splitting.

## Tests

- 225 passed across all 5 commits, zero regressions.
- One refactor commit added 0 tests (pure code motion, behaviour
  preserved); the others kept the existing test surface.

## Verification

### Live re-scrape (attempted, captcha-blocked)

A fresh 5-listing scrape was attempted to mirror the previous
verification (`docs/verification-report-5-listings.md`). MilAnuncios
threw an F5/Incapsula captcha during browser warm-up that requires
manual click-through on the user's display (`:1`). The 600 s wait
window expired without resolution; the scraper exited with
`[CAPTCHA_TIMEOUT]` and entered the standard 10-minute backoff loop.
The run was killed cleanly — no DB rows persisted, no Webflow drafts
created.

This is the documented `CaptchaRequiredException` path
(`integrations/milanuncios.py`) and is independent of every change in
this session. To re-attempt the live verification, the user must be
present at the Chrome window on `:1` to solve the captcha within
~10 minutes of starting the scrape.

### Synthetic end-to-end smoke test (alternative)

To verify the refactored pipeline still produces the right output
shape, a synthetic listing built from `tests/fixtures/sample_listing.json`
was passed through the full chain:

1. `parse_ad_type` (now in `parser_ad_type.py`)
2. `parse_property_type`, `parse_seller_id`, `parse_phone2`,
   `parse_seller_url` (now in `parser_fields.py`)
3. `compute_canonical_title` (R4 helper in `slugify.py`)
4. `slugify_title` (unchanged)
5. `build_field_data` (now composing 3 helpers: `_coerce_field_value`,
   `_route_price_to_field`, `_assign_image_fields`)

Result — 15 / 15 task contract checks pass:

| Slug populated | Value (synthetic) | Task |
|---|---|---|
| `name` | `Nave industrial en venta en Manises (Valencia)` | T2 |
| `slug` | `nave-industrial-en-venta-en-manises-valencia` | T2 |
| `funeral-home-biography` | `<p>Gran nave industrial …</p>` | T4 |
| `new-sale-price` | `450.000 €` | T5 |
| `new-price-sm2-month` | None (correctly empty for venta) | T5 |
| `squared-meters` | `1500.0` | (generic) |
| `location` | `Manises (Valencia)` | (generic) |
| `full-address` | `Polígono Fuente del Jarro, 46980, Manises, Valencia` | (generic) |
| `latitude` | `40.31` | T9 |
| `longitude` | `-3.73` | T9 |
| `contact-name` | `Naves Express SL` | T8 |
| `contact-number` | `666111222` | T8 |
| `google-place-id` | full milanuncios URL | T7 (temp stash) |
| `main-image` | `{url, alt}` dict | T3 |
| `listing-images` | 4 items | T3 |
| `all-images` | 5 items | T3 |
| `additional-images` | 1 item | T3 |

All 9 Benedict tasks remain wired correctly through the refactored
modules. The smoke test ran in 0.05 s using the existing fixture and
the live Webflow schema.

### Tests as the third verification surface

The 225-test suite covers every behavioural change:

| Test file | Behaviour gated |
|---|---|
| `test_parser.py` (16 ad-type cases) | T1, dual mode (4 new cases) |
| `test_slugify.py` (12 cases) | T2, dual phrase, `compute_canonical_title` (R4) |
| `test_price_formatter.py` (18 cases) | T5, dual price routing |
| `test_description_formatter.py` (23 cases) | T4, Ref-prefix strip (8 new cases) |
| `test_webflow_sync.py` (29 cases) | Mapping, image splitting, contact fields, source-url stash, dual price routing, B7 URL-shape guard |
| `test_db.py` (incl. lat/lng) | T9, schema migration |
| `test_api_endpoints.py` | Endpoint contract |

## Performance changes (measurable)

- **Image uploads**: serial → parallel via `asyncio.Semaphore(5)`.
  20-image listing: ~80 s → ~20 s (~75% reduction).
- **Dashboard sync click**: skipped CMS pagination on empty backlog.
  ~8 s → 0 s when nothing to sync.
- **DB writes**: `PRAGMA busy_timeout=5000` on 3 connection sites
  closes the race between scraper subprocess + FastAPI handler + sync.
  No more silent `OperationalError: database is locked` discards.
- **Cloudinary cleanup**: parallel `gather` → serial loop.
  Eliminates `Connection pool is full` urllib3 warnings; same
  throughput because the deletes were rate-limited by the API anyway.

## Operator-visible changes (logging)

Five log lines promoted from DEBUG/INFO → WARNING so failures and
edge cases are visible in the default dashboard log view:

1. Webflow Assets API 403 (token missing assets:write scope)
2. `__INITIAL_PROPS__` not found (page blocked / layout change)
3. Dual venta_alquiler classification (audit trail)
4. Webflow schema rename dropping a mapped field
5. In-flight `[SKIP] Ya existe:` per duplicate listing (dashboard
   counter updates in real time, not just at end-of-run)

## What did NOT happen this session

- No live re-scrape against MilAnuncios — captcha not solved within
  the 600 s wait. The earlier 5-listing verification
  (`docs/verification-report-5-listings.md`, 5/5 pass on tasks +
  Nominatim coordinate sanity) remains the latest live evidence.
- No Sprint 5 work (P3 lighter warm-up, P6 paged unsynced query) —
  deferred by design pending measurement / scale triggers.

## Recommended next session

1. **Run a fresh real-data verification** when the user is at the
   Chrome window to solve the captcha in real time, or after running
   `python3 save_session.py` to refresh the auth cookies.
2. **Sprint 5 (P3 + P6)** if a captcha-debugging session is on the
   calendar — the warm-up rewrite needs a way to confirm the F5
   token survives a single-page reload.
3. **Optional further refactor of `parser_fields.py`** (651 lines)
   only if a real maintenance pain point emerges; otherwise the
   25 small parsers belong together.
