"""
One-shot backfill to assign the Spanish locale to existing Webflow CMS items.

When items were created before locale support was added to the sync pipeline,
they only exist in the primary locale (no Spanish variant). This script
PATCHes each item to create/update its Spanish locale variant.

Usage:
    python scripts/backfill_locale.py --dry-run
    python scripts/backfill_locale.py --listing-id 123456789
    python scripts/backfill_locale.py
"""
import argparse
import asyncio
import logging
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from integrations.webflow_client import WebflowClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s -- %(message)s",
)
logger = logging.getLogger("backfill_locale")

DB_PATH = os.getenv("DB_PATH", "naves.db")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill Spanish locale on Webflow CMS items")
    parser.add_argument("--dry-run", action="store_true", help="Do not write changes")
    parser.add_argument("--listing-id", type=str, default=None, help="Only process this listing")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()

    if args.dry_run:
        logger.info("[backfill_locale] DRY RUN -- no changes will be written")

    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    sql = """
        SELECT listing_id, webflow_item_id
        FROM listings
        WHERE webflow_item_id IS NOT NULL
          AND webflow_item_id != ''
          AND webflow_item_id != 'DUPLICATE'
    """
    params: list = []
    if args.listing_id:
        sql += " AND listing_id = ?"
        params.append(args.listing_id)

    rows = conn.execute(sql, params).fetchall()
    total = len(rows)
    logger.info("[backfill_locale] %d items to process", total)

    if total == 0:
        conn.close()
        return 0

    patched = 0
    failed = 0

    try:
        async with WebflowClient() as client:
            spanish_locale_id = await client.resolve_spanish_locale_id()
            if not spanish_locale_id:
                logger.error(
                    "[backfill_locale] Spanish locale not found. "
                    "Ensure the site has localization enabled with a Spanish locale."
                )
                return 1

            for i, row in enumerate(rows, start=1):
                listing_id = row["listing_id"]
                item_id = row["webflow_item_id"]

                if args.dry_run:
                    logger.info(
                        "[backfill_locale][dry-run] %s -> PATCH item %s with locale %s",
                        listing_id, item_id, spanish_locale_id,
                    )
                    patched += 1
                    continue

                result = await client.update_items(
                    [{"id": item_id, "fieldData": {}}],
                    cms_locale_id=spanish_locale_id,
                )
                if result["errors"]:
                    logger.error(
                        "[backfill_locale] %s: PATCH failed: %s",
                        listing_id, result["errors"],
                    )
                    failed += 1
                else:
                    patched += 1

                await asyncio.sleep(0.6)

                if i % 10 == 0:
                    logger.info("[backfill_locale] progress: %d/%d", i, total)
    finally:
        conn.close()

    logger.info(
        "[backfill_locale] done -- patched=%d, failed=%d, total=%d",
        patched, failed, total,
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
