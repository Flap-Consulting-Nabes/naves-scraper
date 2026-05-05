# Plan — execute all 21 findings from Codex review (2026-05-04)

**Status:** Sprints 1-3 complete. Sprint 4 partial (R1 split deferred).
Sprint 5 deferred as planned. Test suite green throughout (225 passed).

Source: `docs/codex-review-2026-05-04.md`. Each step lists the finding ID,
files touched, and the test gate that must pass before the commit.

The plan is grouped into 5 sprints by risk and dependency. Each sprint
ends with a commit and a green test suite (currently 225 passing).

## Completion log

| Sprint | Commit | Status |
|---|---|---|
| Sprint 1 | `475363a` | ✅ All 5 items done (B1, B2, B8, R5, R6) |
| Sprint 2 | `cd6cc45` | ✅ All 3 items done (P1, P2, P5) |
| Sprint 3 | `ff79469` | ✅ All 6 items done (B3, B4, B5, B6, B7, B9 — B9 was already in Sprint 1) |
| Sprint 4 | `d158e96` | ✅ R2, R3, R4 done. R1 partial (ad_type extracted, full split deferred) |
| Sprint 5 | — | ⏸ Deferred as planned (P3, P6) |

---

## Sprint 1 — Foundations + quick wins (commit 1)

| # | ID | Change | Files | Test gate |
|---|---|---|---|---|
| 1 | R5 | Delete 5 orphan test files at repo root | `test_api.py`, `test_api2.py`, `test_error.py`, `test_launch.py`, `test_tabs.py` | full suite |
| 2 | B1 | Default `DISPLAY=:99` to match Xvfb | `api/scraper_job.py:272` | targeted |
| 3 | B2 | `PRAGMA busy_timeout=5000` on 3 connection sites | `db.py::init_db`, `api/dependencies.py::get_db`, `webflow_sync.py::sync_pending_listings` | full suite |
| 4 | B8 | Hoist `import re` to module top | `api/scraper_job.py` | full suite |
| 5 | R6 | Promote unmatched-fields log to `WARNING` | `webflow_sync.py:91-93` | full suite |

## Sprint 2 — Performance quick wins (commit 2)

| # | ID | Change | Files |
|---|---|---|---|
| 6 | P1 | Parallelize per-listing image uploads with `asyncio.Semaphore(5)` | `webflow_image_uploader.py` |
| 7 | P2 | Skip `_build_source_url_index` when no unsynced rows | `webflow_sync.py::sync_pending_listings` |
| 8 | P5 | Serialize Cloudinary `delete_images` (off critical path) | `cloudinary_client.py::delete_images` |

## Sprint 3 — Correctness bug fixes (commit 3)

| # | ID | Change | Files |
|---|---|---|---|
| 9 | B3 | Catch HTTP 403 explicitly in `upload_asset`; raise log level on fallback | `webflow_client.py::upload_asset`, `webflow_image_uploader.py:94` |
| 10 | B4 | Warn loudly when `__INITIAL_PROPS__` is missing | `parser.py::parse_initial_props_json` (or its call site) |
| 11 | B5 | Cache `parse_title` / `parse_description` results in `parse_listing_page` | `parser.py:933,956` |
| 12 | B6 | Promote dual-classification log to `WARNING` | `parser.py::parse_ad_type` |
| 13 | B7 | Filter non-URL values out of dedup index; document in decision doc | `webflow_sync.py::_build_source_url_index`, `docs/decisions/2026-05-04-source-url-temp-stash.md` |
| 14 | B9 | Real-time `total_skipped` counter from `[SKIP] Ya existe:` lines | `api/scraper_job.py::_monitor_proc` |

## Sprint 4 — Refactors (one commit per file split)

| # | ID | Change | Files |
|---|---|---|---|
| 15 | R3 | Split `db.py` into `db/__init__.py` (re-exports) + `db/_schema.py` + `db/_init.py` + `db.py` (CRUD) | `db.py` → 3 modules under cap |
| 16 | R1 | Split `parser.py` into `parser_core.py` + `parser_fields.py` + `parser_ad_type.py` + `parser_listing.py` (or sub-package) | `integrations/parser.py` → 4 modules |
| 17 | R2 | Extract `_route_price_to_field` and `_assign_image_fields` helpers | `webflow_sync.py::build_field_data` |
| 18 | R4 | Extract `utils/listing_metadata.py::compute_listing_metadata` shared between scraper + migrate | `scraper_engine.py:220-235`, `scripts/migrate_existing_listings.py:101-156` |

## Sprint 5 — Deferred items

These are kept as todos but **not** auto-applied because the risk/payoff
profile needs human input:

- **P3** (lighter browser warm-up on rotation) — needs measurement of
  whether a one-page reload preserves the F5/Incapsula token. Defer
  until next captcha-debugging session.
- **P6** (paged `get_unsynced_listings`) — only matters when the unsynced
  backlog grows past ~1000 rows. Defer until the migration script needs it.

## Commit cadence

After each sprint:

1. `python3 -m pytest tests/ -q` must show **225+ passed, 0 failed**
   (the count grows as new tests are added per refactor).
2. Single commit with the sprint label and a one-line per-finding bullet
   list in the body.

## Verification at the end

After Sprint 4, the same 5-listing real-data verification used in
`docs/verification-report-5-listings.md` must pass identically. No
behavioural regression is acceptable — all 21 findings are diagnostic,
documentation, or non-functional refactors except the parallel-upload
change (P1) which only affects timing.
