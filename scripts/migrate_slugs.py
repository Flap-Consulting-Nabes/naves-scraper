"""
One-shot migration to the title-based unique slug system.

Phases (each idempotent, safe to re-run, and individually skippable):

  A. DB migration — init_db() adds the webflow_slug column via _NEW_COLUMNS
  B. Back-fill webflow_slug for rows where it is NULL (oldest-first so the
     earliest listing keeps the bare slug and later collisions get `-2`, `-3`…)
  C. Rename images on disk to `{slug}-image-{i}.{ext}` and rewrite
     listings.images_local  (see scripts/_rename_listing_images.py)
  D. PATCH existing Webflow items with the new slug (batches of <=100)
  E. Reset legacy DUPLICATE markers so those rows will be re-created fresh
     on the next normal sync

Usage:
    python scripts/migrate_slugs.py --dry-run
    python scripts/migrate_slugs.py
    python scripts/migrate_slugs.py --skip-webflow
    python scripts/migrate_slugs.py --skip-images
"""
import argparse
import asyncio
import logging
import os
import sqlite3
import sys
from pathlib import Path

# Allow running the script directly from the project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from db import (
    init_db,
    get_all_listings_for_migration,
    update_webflow_slug,
)
from integrations.webflow_client import WebflowClient
from utils.slugify import generate_unique_slug

from scripts._rename_listing_images import rename_images

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("migrate_slugs")

DB_PATH = os.getenv("DB_PATH", "naves.db")
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def backfill_slugs(conn: sqlite3.Connection, dry_run: bool) -> dict:
    """Phase B — assign webflow_slug to every row that lacks one."""
    rows = get_all_listings_for_migration(conn)
    total = len(rows)
    logger.info("[Phase B] %d listings scanned", total)

    assigned = 0
    skipped = 0

    for i, row in enumerate(rows, start=1):
        listing_id = row["listing_id"]
        if row.get("webflow_slug"):
            skipped += 1
            continue

        new_slug = generate_unique_slug(
            conn, row.get("title"), listing_id, exclude_listing_id=listing_id
        )
        if dry_run:
            logger.info("[Phase B][dry-run] %s → %s", listing_id, new_slug)
        else:
            update_webflow_slug(conn, listing_id, new_slug)
        assigned += 1

        if i % 50 == 0:
            logger.info("[Phase B] progress: %d/%d", i, total)

    logger.info(
        "[Phase B] done — assigned=%d, already_set=%d, total=%d",
        assigned, skipped, total,
    )
    return {"assigned": assigned, "skipped": skipped, "total": total}


async def resync_webflow(conn: sqlite3.Connection, dry_run: bool) -> dict:
    """Phase D — PATCH existing Webflow items with the new title-based slug."""
    rows = conn.execute(
        """
        SELECT listing_id, webflow_item_id, webflow_slug
        FROM listings
        WHERE webflow_item_id IS NOT NULL
          AND webflow_item_id != ''
          AND webflow_item_id != 'DUPLICATE'
          AND webflow_slug IS NOT NULL
        """
    ).fetchall()
    total = len(rows)
    logger.info("[Phase D] %d Webflow items to re-sync", total)

    if total == 0:
        return {"updated": 0, "errors": []}

    updates = [
        {"id": row["webflow_item_id"], "fieldData": {"slug": row["webflow_slug"]}}
        for row in rows
    ]

    if dry_run:
        logger.info("[Phase D][dry-run] would PATCH %d items", total)
        for u in updates[:5]:
            logger.info("[Phase D][dry-run] sample: %s", u)
        return {"updated": total, "errors": []}

    async with WebflowClient() as client:
        result = await client.update_items(updates)

    logger.info(
        "[Phase D] done — updated=%d, errors=%d",
        result["updated"], len(result["errors"]),
    )
    return result


def reset_duplicate_markers(conn: sqlite3.Connection, dry_run: bool) -> dict:
    """Phase E — clear legacy DUPLICATE markers so they re-sync fresh."""
    count = conn.execute(
        "SELECT COUNT(*) FROM listings WHERE webflow_item_id = 'DUPLICATE'"
    ).fetchone()[0]
    if count == 0:
        logger.info("[Phase E] nothing to reset")
        return {"reset": 0}

    if dry_run:
        logger.info("[Phase E][dry-run] would reset %d DUPLICATE markers", count)
        return {"reset": count}

    conn.execute(
        "UPDATE listings "
        "SET webflow_item_id = NULL, webflow_synced_at = NULL "
        "WHERE webflow_item_id = 'DUPLICATE'"
    )
    conn.commit()
    logger.info("[Phase E] reset %d DUPLICATE markers", count)
    return {"reset": count}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Title-based slug migration")
    parser.add_argument("--dry-run", action="store_true", help="Do not write changes")
    parser.add_argument("--skip-images", action="store_true", help="Skip Phase C (rename images)")
    parser.add_argument("--skip-webflow", action="store_true", help="Skip Phase D (Webflow re-sync)")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()

    if args.dry_run:
        logger.info("[migrate_slugs] DRY RUN — no changes will be written")

    # Phase A — DB migration via init_db
    logger.info("[Phase A] initialising DB schema")
    conn = init_db(DB_PATH)

    try:
        backfill_result = backfill_slugs(conn, args.dry_run)

        if args.skip_images:
            logger.info("[Phase C] skipped")
            image_result: dict = {"skipped_phase": True}
        else:
            image_result = rename_images(conn, PROJECT_ROOT, args.dry_run)

        if args.skip_webflow:
            logger.info("[Phase D] skipped")
            webflow_result: dict = {"skipped_phase": True}
        else:
            webflow_result = await resync_webflow(conn, args.dry_run)

        reset_result = reset_duplicate_markers(conn, args.dry_run)
    finally:
        conn.close()

    logger.info("=" * 60)
    logger.info("Migration summary")
    logger.info("  Phase B (backfill)   : %s", backfill_result)
    logger.info("  Phase C (rename)     : %s", image_result)
    logger.info("  Phase D (webflow)    : %s", webflow_result)
    logger.info("  Phase E (duplicates) : %s", reset_result)
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
