"""
One-shot migration to canonical title + slug format.

Iteración 2026-05 (Tarea 2). For every listing in the DB:

  1. Capture the current `title` into `original_title` (idempotent — only if
     `original_title IS NULL`).
  2. Compute `{Name}` via `extract_warehouse_name`. Skip the row when no
     usable name can be derived (logged as WARN).
  3. Build the canonical title `Nave industrial en {tipo} en {Name}` via
     `build_canonical_title`. Skip if `ad_type` is missing.
  4. Recompute `webflow_slug` with `generate_unique_slug` (collision-aware).
  5. UPDATE the local row with new title + slug + original_title.
  6. PATCH the corresponding Webflow item with the new `name` and `slug`.
  7. Emit a CSV report: `migration_canonical_titles_{ts}.csv` listing all
     changes (`listing_id, old_title, new_title, old_slug, new_slug, status`).
  8. Emit a redirects CSV: `redirects_{ts}.csv` with `old_slug,new_slug` for
     every row whose slug changed — Benedict can paste it into Webflow Site
     Settings → Hosting → Redirects to keep public URLs from 404'ing.

The script is `--dry-run` by default. Pass `--apply` (and optionally
`--yes` to skip the interactive confirmation) to actually write changes.

Usage:
    python scripts/migrate_canonical_titles.py
    python scripts/migrate_canonical_titles.py --apply
    python scripts/migrate_canonical_titles.py --apply --yes
    python scripts/migrate_canonical_titles.py --apply --skip-webflow
"""
import argparse
import asyncio
import csv
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
from integrations.webflow_client import WebflowClient
from utils.slugify import (
    build_canonical_title,
    extract_warehouse_name,
    generate_unique_slug,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("migrate_canonical_titles")

DB_PATH = os.getenv("DB_PATH", "naves.db")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = PROJECT_ROOT / "reports"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="Write changes (default is dry-run, no DB or Webflow writes).",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="Skip the interactive confirmation prompt before --apply.",
    )
    parser.add_argument(
        "--skip-webflow", action="store_true",
        help="Update local DB only; do not PATCH the Webflow CMS.",
    )
    parser.add_argument(
        "--listing-id", type=str, default=None,
        help="Process only this listing_id (useful for testing).",
    )
    return parser.parse_args()


def fetch_rows(conn: sqlite3.Connection, only: str | None) -> list[dict]:
    sql = """
        SELECT listing_id, title, original_title, webflow_slug, webflow_item_id,
               ad_type, address, location
        FROM listings
        ORDER BY scraped_at ASC
    """
    params: tuple = ()
    if only:
        sql = sql.replace("ORDER BY", "WHERE listing_id = ?\n        ORDER BY")
        params = (only,)
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def plan_changes(rows: list[dict]) -> list[dict]:
    """Compute the proposed change for each row without writing anything."""
    changes: list[dict] = []
    # Pre-load existing slugs so generate_unique_slug picks deterministic
    # numbering — we feed the in-memory DB connection into the helper, so
    # this preload is implicit. The helper queries the DB directly.
    for row in rows:
        listing_id = row["listing_id"]
        old_title = row.get("title") or ""
        old_slug = row.get("webflow_slug") or ""
        canonical_name = extract_warehouse_name(row)
        new_title = build_canonical_title(row.get("ad_type"), canonical_name)

        if not new_title:
            changes.append({
                "listing_id": listing_id,
                "old_title": old_title,
                "new_title": "",
                "old_slug": old_slug,
                "new_slug": "",
                "status": "skipped_no_canonical",
            })
            continue

        if new_title == old_title:
            changes.append({
                "listing_id": listing_id,
                "old_title": old_title,
                "new_title": new_title,
                "old_slug": old_slug,
                "new_slug": old_slug,
                "status": "noop",
            })
            continue

        changes.append({
            "listing_id": listing_id,
            "old_title": old_title,
            "new_title": new_title,
            "old_slug": old_slug,
            "new_slug": "",  # filled in below per-row when applying
            "status": "pending",
            "row": row,
        })
    return changes


def write_reports(changes: list[dict], ts: str) -> tuple[Path, Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    main_path = REPORT_DIR / f"migration_canonical_titles_{ts}.csv"
    redirects_path = REPORT_DIR / f"redirects_{ts}.csv"

    with main_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["listing_id", "old_title", "new_title", "old_slug", "new_slug", "status"])
        for c in changes:
            writer.writerow([
                c["listing_id"], c["old_title"], c["new_title"],
                c["old_slug"], c["new_slug"], c["status"],
            ])

    with redirects_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["old_slug", "new_slug"])
        for c in changes:
            if c["old_slug"] and c["new_slug"] and c["old_slug"] != c["new_slug"]:
                writer.writerow([c["old_slug"], c["new_slug"]])

    return main_path, redirects_path


async def patch_webflow_items(
    client: WebflowClient,
    pending: list[dict],
    locale_id: str | None,
) -> dict:
    """PATCH Webflow items in batches of 100 with the new name + slug."""
    updates: list[dict] = []
    for c in pending:
        item_id = c["row"].get("webflow_item_id")
        if not item_id or item_id == "DUPLICATE":
            continue
        updates.append({
            "id": item_id,
            "fieldData": {"name": c["new_title"], "slug": c["new_slug"]},
        })
    if not updates:
        logger.info("[Webflow] No items to PATCH (no webflow_item_id on changed rows).")
        return {"updated": 0, "errors": []}
    return await client.update_items(updates, cms_locale_id=locale_id)


async def run() -> int:
    args = parse_args()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    mode = "APPLY" if args.apply else "DRY-RUN"
    logger.info("[migrate_canonical_titles] mode=%s ts=%s", mode, ts)

    conn = init_db(DB_PATH)
    try:
        rows = fetch_rows(conn, args.listing_id)
        logger.info("[migrate_canonical_titles] %d rows scanned", len(rows))

        changes = plan_changes(rows)
        pending = [c for c in changes if c["status"] == "pending"]
        skipped = [c for c in changes if c["status"] == "skipped_no_canonical"]
        noop = [c for c in changes if c["status"] == "noop"]

        logger.info(
            "[migrate_canonical_titles] pending=%d  skipped=%d  noop=%d",
            len(pending), len(skipped), len(noop),
        )

        if args.apply and pending and not args.yes:
            print(f"\nAbout to apply {len(pending)} changes (DB + "
                  f"{'skip Webflow' if args.skip_webflow else 'Webflow PATCH'}).")
            answer = input("Type 'yes' to continue: ")
            if answer.strip().lower() != "yes":
                logger.warning("Aborted by user.")
                return 1

        # Compute new slugs by replaying generate_unique_slug per row, in the
        # original scraped_at order, so the helper sees prior rows already
        # updated and assigns deterministic suffixes.
        for c in pending:
            row = c["row"]
            new_slug = generate_unique_slug(
                conn, c["new_title"], row["listing_id"],
                exclude_listing_id=row["listing_id"],
            )
            c["new_slug"] = new_slug

            if args.apply:
                update_canonical_title(
                    conn,
                    row["listing_id"],
                    c["new_title"],
                    new_slug,
                    row.get("title"),  # current title becomes original_title
                )

        if args.apply and pending and not args.skip_webflow:
            async with WebflowClient() as client:
                locale_id = await client.resolve_spanish_locale_id()
                result = await patch_webflow_items(client, pending, locale_id)
                logger.info(
                    "[Webflow] PATCH result: updated=%d errors=%d",
                    result["updated"], len(result["errors"]),
                )
                for err in result["errors"]:
                    logger.error("[Webflow] %s", err)

        main_csv, redirects_csv = write_reports(changes, ts)
        logger.info("[migrate_canonical_titles] report:    %s", main_csv)
        logger.info("[migrate_canonical_titles] redirects: %s", redirects_csv)
        if not args.apply:
            logger.info("Run with --apply to write changes.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
