"""Re-scrape phone numbers for already-stored listings and push the
correction to Webflow CMS.

Background: an early version of `parse_phone()` returned the agency's
shop-level phone (`shop.phone1`) instead of the listing-specific
`tel:` link revealed after clicking the call button. The scraper has
been fixed; this script backfills rows persisted under the old logic.

Usage:
    python scripts/refresh_phones.py --dry-run   # show diffs only
    python scripts/refresh_phones.py             # update DB + Webflow

By default it processes every row that has a non-null URL. Use
`--listing-id` to limit to one ID for testing.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")

from db import init_db
from integrations.milanuncios import close_browser, get_browser, scrape_listing
from integrations.webflow_client import WebflowClient
from integrations.webflow_sync import resolve_field_mapping

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


async def fetch_phones(url: str) -> tuple[str | None, str | None]:
    data = await scrape_listing(url)
    return data.get("phone"), data.get("phone2")


async def patch_webflow(item_id: str, phone: str, locale_id: str | None) -> bool:
    async with WebflowClient() as wf:
        schema = await wf.get_collection_schema()
        mapping = resolve_field_mapping(schema)
        slug = mapping.get("phone")
        if not slug:
            logger.warning("[Webflow] No phone slug in collection schema — skipping PATCH")
            return False
        result = await wf.update_items(
            [{"id": item_id, "fieldData": {slug: phone}}],
            cms_locale_id=locale_id,
        )
        if result["errors"]:
            logger.error("[Webflow] update errors: %s", result["errors"])
            return False
        return result["updated"] > 0


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--listing-id", help="Only process this listing_id")
    args = parser.parse_args()

    conn = init_db()
    conn.row_factory = sqlite3.Row
    rows = list(
        conn.execute(
            "SELECT listing_id, url, phone, phone2, webflow_item_id "
            "FROM listings WHERE url IS NOT NULL"
            + (" AND listing_id = ?" if args.listing_id else "")
            + " ORDER BY id DESC",
            (args.listing_id,) if args.listing_id else (),
        )
    )
    if not rows:
        logger.info("No rows to process.")
        return

    logger.info("Refreshing %d listings (dry_run=%s)", len(rows), args.dry_run)

    locale_id: str | None = None
    if not args.dry_run:
        async with WebflowClient() as wf:
            locale_id = await wf.resolve_spanish_locale_id()

    await get_browser()

    updated_db = 0
    updated_wf = 0
    unchanged = 0
    failed = 0

    for row in rows:
        listing_id = row["listing_id"]
        url = row["url"]
        old_phone = row["phone"]
        wf_item_id = row["webflow_item_id"]
        try:
            new_phone, new_phone2 = await fetch_phones(url)
        except Exception as e:
            logger.error("[%s] scrape failed: %s", listing_id, e)
            failed += 1
            continue

        if new_phone is None:
            logger.warning("[%s] new phone is None — skipping", listing_id)
            failed += 1
            continue

        if new_phone == old_phone:
            logger.info("[%s] phone unchanged (%s)", listing_id, old_phone)
            unchanged += 1
            continue

        logger.info("[%s] phone %s -> %s", listing_id, old_phone, new_phone)

        if args.dry_run:
            continue

        conn.execute(
            "UPDATE listings SET phone = ?, phone2 = ?, updated_at = ? WHERE listing_id = ?",
            (new_phone, new_phone2, datetime.now(timezone.utc).isoformat(), listing_id),
        )
        conn.commit()
        updated_db += 1

        if wf_item_id:
            ok = await patch_webflow(wf_item_id, new_phone, locale_id)
            if ok:
                updated_wf += 1
            else:
                failed += 1

    await close_browser()

    logger.info(
        "Done. db_updated=%d webflow_updated=%d unchanged=%d failed=%d",
        updated_db, updated_wf, unchanged, failed,
    )


if __name__ == "__main__":
    asyncio.run(main())
