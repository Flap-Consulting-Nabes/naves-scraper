"""
Comprehensive migration of every already-scraped listing to the May 2026
client-feedback rules.

Iteración 2026-05 (Bloque G1). One-shot script that re-applies *all* the
new behaviours of this iteration to rows already in the local DB and to
the corresponding Webflow CMS items:

  1. Recompute `ad_type` (re-parses url + raw_html when stored).
  2. Reformat the `price` display string via `format_price_display` so
     the Webflow field reflects "199.000 €" / "1.19€/m²" / "1.500 €/mes".
  3. Convert `description` to RichText HTML via `format_description_html`.
  4. Recompute the canonical title + slug (preserves `original_title`).
  5. Re-derive lat/lng from `raw_html` when missing in the row.
  6. Force a fresh image split (main / top4 / all-5 / additional) — only
     reshuffles existing image URLs, no re-download.
  7. Sends the updated `fieldData` to Webflow via `update_items`.

Usage (defaults to dry-run):
    python scripts/migrate_existing_listings.py
    python scripts/migrate_existing_listings.py --apply
    python scripts/migrate_existing_listings.py --apply --skip-webflow
    python scripts/migrate_existing_listings.py --listing-id 123456789

Outputs:
    reports/migration_existing_{ts}.csv  (per-row diff: which fields changed)
"""
import argparse
import asyncio
import csv
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from db import init_db, update_canonical_title
from integrations.parser import (
    parse_ad_type,
    parse_coordinates,
    parse_initial_props_json,
)
from integrations.webflow_client import WebflowClient
from integrations.webflow_sync import (
    FIELD_MAP_PATTERNS,
    build_field_data,
    resolve_field_mapping,
)
from utils.description_formatter import format_description_html
from utils.price_formatter import format_price_display
from utils.slugify import (
    compute_canonical_title,
    generate_unique_slug,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("migrate_existing_listings")

DB_PATH = os.getenv("DB_PATH", "naves.db")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = PROJECT_ROOT / "reports"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Write changes (default is dry-run).")
    parser.add_argument("--yes", action="store_true",
                        help="Skip the interactive confirmation prompt.")
    parser.add_argument("--skip-webflow", action="store_true",
                        help="Update local DB only; do not PATCH Webflow.")
    parser.add_argument("--listing-id", type=str, default=None,
                        help="Process only this listing_id.")
    return parser.parse_args()


def fetch_rows(conn: sqlite3.Connection, only: str | None) -> list[dict]:
    sql = """
        SELECT * FROM listings ORDER BY scraped_at ASC
    """
    if only:
        sql = "SELECT * FROM listings WHERE listing_id = ? ORDER BY scraped_at ASC"
        rows = conn.execute(sql, (only,)).fetchall()
    else:
        rows = conn.execute(sql).fetchall()
    return [dict(r) for r in rows]


def recompute_row(row: dict) -> dict:
    """Return a dict of changes to apply to this row.

    Keys present mean the value differs from current; absent keys keep
    the existing value. Decisions:
      - `ad_type`: re-parse from url + raw_html if currently NULL.
      - `latitude`/`longitude`: derive from raw_html if missing.
      - `title` + `webflow_slug`: canonicalize (when ad_type+name available).
      - `description`: rewrite to HTML if not already wrapped in tags.
      - `price`: leave the local value untouched; the formatted string is
        derived at sync time from price_numeric/price_per_m2.
    """
    proposed: dict = {}

    # ── ad_type ──
    # Iteración 2026-05-04: re-evaluar SIEMPRE el tipo, no solo cuando es
    # NULL. El body-scan reforzado (parse_ad_type capa 4) puede corregir
    # listings categorizados erróneamente por la fuente.
    ad_json = _ad_json_from_raw_html(row.get("raw_html"))
    new_ad = parse_ad_type(
        row.get("url") or "",
        ad_json=ad_json,
        title=row.get("title") or row.get("original_title"),
        description=row.get("description"),
    )
    if new_ad and new_ad != row.get("ad_type"):
        proposed["ad_type"] = new_ad

    ad_type = proposed.get("ad_type") or row.get("ad_type")

    # ── coordinates ──
    if row.get("latitude") is None or row.get("longitude") is None:
        ad_json = _ad_json_from_raw_html(row.get("raw_html"))
        lat, lng = parse_coordinates(ad_json)
        if lat is not None and row.get("latitude") is None:
            proposed["latitude"] = lat
        if lng is not None and row.get("longitude") is None:
            proposed["longitude"] = lng

    # ── description (only mark changed when output differs) ──
    raw_desc = row.get("description")
    if raw_desc and not raw_desc.lstrip().startswith("<"):
        html = format_description_html(raw_desc)
        if html and html != raw_desc:
            proposed["description"] = html

    # ── canonical title + slug ──
    # Pass the (possibly flipped) ad_type into the helper by overlaying
    # it on a copy of the row dict; `compute_canonical_title` reads it
    # back out and forwards to extract_warehouse_name + build_canonical_title.
    canonical_title = compute_canonical_title({**row, "ad_type": ad_type})
    if canonical_title and canonical_title != row.get("title"):
        proposed["title"] = canonical_title
        proposed["original_title"] = row.get("original_title") or row.get("title")
        # Slug is recomputed at apply time so collisions stay deterministic.

    return proposed


def _ad_json_from_raw_html(raw_html: str | None) -> dict | None:
    """Extract the `__INITIAL_PROPS__.ad` JSON block from a raw HTML blob.

    Used by the migration to re-derive ad_type and coordinates from rows
    scraped before those fields were extracted. Returns None when the
    HTML is missing or the block can't be parsed.
    """
    if not raw_html:
        return None
    try:
        props = parse_initial_props_json(raw_html)
    except Exception:
        return None
    return props.get("ad") if props else None


def write_report(diffs: list[dict], ts: str) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"migration_existing_{ts}.csv"
    fieldnames = [
        "listing_id", "fields_changed",
        "old_title", "new_title", "old_slug", "new_slug",
        "ad_type", "status",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for d in diffs:
            writer.writerow({k: d.get(k, "") for k in fieldnames})
    return path


async def patch_webflow(
    client: WebflowClient,
    schema: dict,
    rows_with_changes: list[dict],
    locale_id: str | None,
) -> dict:
    """Build per-item PATCH payloads via build_field_data and send in batches."""
    field_mapping = resolve_field_mapping(schema)
    collection_fields = schema.get("fields", [])
    updates: list[dict] = []
    for row in rows_with_changes:
        item_id = row.get("webflow_item_id")
        if not item_id or item_id == "DUPLICATE":
            continue
        # Decode photos into URL list for the image split helper.
        try:
            image_urls = json.loads(row.get("photos") or "null") or []
        except (TypeError, json.JSONDecodeError):
            image_urls = []
        field_data = build_field_data(row, field_mapping, image_urls, collection_fields)
        # Strip required keys that PATCH does not need to overwrite if absent
        # (Webflow re-uses the existing values).
        updates.append({"id": item_id, "fieldData": field_data})

    if not updates:
        return {"updated": 0, "errors": []}
    return await client.update_items(updates, cms_locale_id=locale_id)


async def run() -> int:
    args = parse_args()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    mode = "APPLY" if args.apply else "DRY-RUN"
    logger.info("[migrate_existing_listings] mode=%s ts=%s", mode, ts)

    conn = init_db(DB_PATH)
    try:
        rows = fetch_rows(conn, args.listing_id)
        logger.info("[migrate_existing_listings] %d rows scanned", len(rows))

        diffs: list[dict] = []
        rows_changed: list[dict] = []
        for row in rows:
            proposed = recompute_row(row)
            if not proposed:
                diffs.append({
                    "listing_id": row["listing_id"],
                    "fields_changed": "",
                    "status": "noop",
                })
                continue

            # Compute new slug only when the title actually changed.
            new_slug = row.get("webflow_slug") or ""
            if "title" in proposed:
                new_slug = generate_unique_slug(
                    conn, proposed["title"], row["listing_id"],
                    exclude_listing_id=row["listing_id"],
                )

            diffs.append({
                "listing_id": row["listing_id"],
                "fields_changed": ",".join(sorted(proposed.keys())),
                "old_title": row.get("title", ""),
                "new_title": proposed.get("title", ""),
                "old_slug": row.get("webflow_slug", ""),
                "new_slug": new_slug if "title" in proposed else "",
                "ad_type": proposed.get("ad_type") or row.get("ad_type") or "",
                "status": "pending",
            })

            # Merge proposed values into a working copy for Webflow PATCH.
            merged = {**row, **proposed}
            if "title" in proposed:
                merged["webflow_slug"] = new_slug
            # Pre-format price for the PATCH payload.
            merged["price"] = format_price_display(
                merged.get("ad_type"),
                merged.get("price_numeric"),
                merged.get("price_per_m2"),
            ) or merged.get("price")
            rows_changed.append(merged)

            if args.apply:
                # 1. Apply title/slug change locally if any.
                if "title" in proposed:
                    update_canonical_title(
                        conn,
                        row["listing_id"],
                        proposed["title"],
                        new_slug,
                        proposed.get("original_title"),
                    )
                # 2. Apply other column updates with a generic UPDATE.
                column_updates = {
                    k: v for k, v in proposed.items()
                    if k not in ("title", "original_title")
                }
                if column_updates:
                    cols = ", ".join(f"{c} = ?" for c in column_updates)
                    conn.execute(
                        f"UPDATE listings SET {cols} WHERE listing_id = ?",
                        list(column_updates.values()) + [row["listing_id"]],
                    )
                    conn.commit()

        pending = [d for d in diffs if d["status"] == "pending"]
        logger.info(
            "[migrate_existing_listings] pending=%d  noop=%d  total=%d",
            len(pending), len(diffs) - len(pending), len(diffs),
        )

        if args.apply and pending and not args.skip_webflow:
            if not args.yes:
                print(f"\nAbout to PATCH {len(pending)} Webflow items.")
                if input("Type 'yes' to continue: ").strip().lower() != "yes":
                    logger.warning("Webflow PATCH aborted by user.")
                    args.skip_webflow = True
            if not args.skip_webflow:
                async with WebflowClient() as client:
                    schema = await client.get_collection_schema()
                    locale = await client.resolve_spanish_locale_id()
                    result = await patch_webflow(client, schema, rows_changed, locale)
                    logger.info(
                        "[Webflow] PATCH result: updated=%d errors=%d",
                        result["updated"], len(result["errors"]),
                    )
                    for err in result["errors"]:
                        logger.error("[Webflow] %s", err)

        report_path = write_report(diffs, ts)
        logger.info("[migrate_existing_listings] report: %s", report_path)
        if not args.apply:
            logger.info("Run with --apply to write changes.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
