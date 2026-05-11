# Decision — Park MilAnuncios source URL in `google-place-id` (temporary)

**Date:** 2026-05-04
**Status:** Active (temporary)
**Owner:** Alejandro
**Affects:** `integrations/webflow_sync.py` → `FIELD_MAP_PATTERNS["url"]`

## Context

Webflow's "Spain Warehouses" collection currently exposes 22 fields. Of the
ones we still owe Benedict, two are relevant here:

| DB field | Intended Webflow slug | Status |
|---|---|---|
| `url` (MilAnuncios listing URL) | `source-url` | Missing — Benedict has not created it |
| Future Google Place ID | `google-place-id` | Already exists, but we do not extract Place IDs yet (geocoding Phase 2) |

The MilAnuncios URL is the canonical de-dup key we want to round-trip through
Webflow (Tareas 6 + 7 in `docs/iteration-2026-05-feedback.md`). Without a slug
to write it to, every sync has to rebuild dedup state from scratch, and
editors who open a CMS item have no link back to the original ad.

## Decision

Until `source-url` is created in Webflow, write the MilAnuncios listing URL
into the existing `google-place-id` slug. We control both the writer
(`webflow_sync.build_field_data`) and the dedup index reader
(`_build_source_url_index`), so the same string lands in the same slot on
write and is read back as the dedup key on the next run — no extra glue
needed.

The field-mapping fallback is encoded in `FIELD_MAP_PATTERNS["url"]`:

```python
"url": ["source-url", "google-place-id", "url", "link", ...]
```

The first slug that exists in the live schema wins. The day Benedict adds
`source-url`, the next sync silently switches over with zero code changes —
new items get the URL on `source-url`, old items keep theirs on
`google-place-id` until a back-fill script moves them.

## Why this slot

- `google-place-id` is a `PlainText` field, identical type to what
  `source-url` will be — no serialization mismatch.
- We do not currently extract Google Place IDs anywhere in the pipeline
  (`db.py` has no `google_place_id` column; the geocoder only stores `lat`
  and `lng`). The slot is unused, so there is no real Google data to
  collide with.
- Lat/lng remain on their own dedicated slugs (`latitude`, `longitude`) and
  are unaffected.

## Safeguards added during Codex review (2026-05-04)

- `_build_source_url_index` now filters values that don't start with
  `http://` / `https://`. If anyone manually pastes a real Google Place
  ID into the slot before Benedict creates `source-url`, the dedup index
  silently skips that entry instead of treating the Place ID as a URL
  and dropping dedup safety for that item.

## Trade-offs

- **Schema lie:** the slug is named `google-place-id` but holds a URL. Anyone
  reading the CMS item directly will be confused. Mitigated by (a) this
  decision doc, (b) the inline comment in `webflow_sync.py` next to the
  `FIELD_MAP_PATTERNS` entry, and (c) the temporary nature.
- **Data loss risk on switchover:** when Benedict creates `source-url`, new
  items will write there and old items will keep the URL on
  `google-place-id`. The cleanup is a one-shot back-fill: copy
  `google-place-id` → `source-url` for every item where the value matches
  `https://www.milanuncios.com/...`, then clear `google-place-id`. No script
  is committed yet — it is owned by the post-`source-url` migration.
- **Phase-2 geocoding conflict:** if we start collecting Place IDs *before*
  Benedict adds `source-url`, the two values will fight for the slot. The
  scraper writer wins (overwrites), so we must not enable Place-ID
  collection until `source-url` lands or this decision is revisited.

## Reversal

When `source-url` exists in the Webflow schema:

1. Re-run `python3 scripts/inspect_webflow_schema.py` and commit the snapshot.
2. The next sync writes new items to `source-url` automatically (first
   match in the candidate list).
3. Run a one-shot back-fill to copy `google-place-id` → `source-url` for
   pre-existing items, then clear `google-place-id` so the slot is free for
   real Place IDs.
4. Remove `"google-place-id"` from `FIELD_MAP_PATTERNS["url"]`.
5. Delete this decision doc (or mark it Resolved and link the back-fill
   commit).

## References

- `integrations/webflow_sync.py:60` — `FIELD_MAP_PATTERNS["url"]` candidates
- `tests/test_webflow_sync.py` → `TestSourceUrlTempStashOnGooglePlaceId`
- `docs/handoff-next-chat.md` — Tarea 7 ("URL original en CMS") still
  blocked on the Webflow side
- `docs/iteration-2026-05-feedback.md` — Tareas 6 + 7 design rationale

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
- Plan: `docs/superpowers/plans/2026-05-10-source-url-migration.md`.

Status: **Resolved**. `google-place-id` is still in the candidate list
as a transitional fallback; remove it in a follow-up PR once the
back-fill has run cleanly in prod.
