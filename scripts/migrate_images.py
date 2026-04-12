"""
One-shot migration to the WebP + Webflow-hosted image system.

Phases (each idempotent, safe to re-run, and individually skippable):

  F. Compress & convert every file in `listings.images_local` to the
     balanced WebP profile (quality=80, max 1200px) and rewrite the JSON
     path list.  See scripts/_compress_listing_images.py.

  G. Re-upload every listing's local `.webp` files to Webflow Assets API
     and PATCH the existing CMS item so `main-image` / `listing-images`
     / `all-images` point at slug-based hosted URLs.  Tracked via the
     `webflow_assets_synced_at` column.  See
     scripts/_upload_assets_to_webflow.py.

Phase G starts with an auth probe — if `WEBFLOW_TOKEN` is missing
`assets:read` / `assets:write`, the script aborts with exit code 2
and a clear message.  Phase F does not need the token.

Usage:
    python scripts/migrate_images.py --dry-run
    python scripts/migrate_images.py --skip-webflow
    python scripts/migrate_images.py --quality 85 --max-dim 1400
    python scripts/migrate_images.py
"""
import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Allow running the script directly from the project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from db import init_db

from scripts._compress_listing_images import compress_images
from scripts._upload_assets_to_webflow import (
    AssetsScopeError,
    upload_and_patch,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("migrate_images")

DB_PATH = os.getenv("DB_PATH", "naves.db")
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="WebP + Webflow asset migration")
    parser.add_argument("--dry-run", action="store_true", help="Do not write changes")
    parser.add_argument(
        "--skip-webflow",
        action="store_true",
        help="Skip Phase G (Webflow asset re-upload)",
    )
    parser.add_argument(
        "--quality",
        type=int,
        default=80,
        help="WebP quality (1-100). Default: 80 (balanced profile).",
    )
    parser.add_argument(
        "--max-dim",
        type=int,
        default=1200,
        help="Long-edge cap in pixels. Default: 1200.",
    )
    parser.add_argument(
        "--listing-id",
        type=str,
        default=None,
        help="Only process this specific listing_id (for end-to-end testing).",
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()

    if args.dry_run:
        logger.info("[migrate_images] DRY RUN — no changes will be written")

    logger.info("[Phase A] initialising DB schema")
    conn = init_db(DB_PATH)

    if args.listing_id:
        logger.info("[migrate_images] targeting single listing_id=%s", args.listing_id)

    try:
        compress_result = compress_images(
            conn,
            PROJECT_ROOT,
            args.dry_run,
            args.quality,
            args.max_dim,
            listing_id_filter=args.listing_id,
        )

        if args.skip_webflow:
            logger.info("[Phase G] skipped")
            upload_result: dict = {"skipped_phase": True}
        else:
            try:
                upload_result = await upload_and_patch(
                    conn, PROJECT_ROOT, args.dry_run,
                    listing_id_filter=args.listing_id,
                )
            except AssetsScopeError as e:
                logger.error("[Phase G] aborting: %s", e)
                logger.error(
                    "[Phase G] fix the token, then re-run "
                    "`python scripts/migrate_images.py`"
                )
                return 2
    finally:
        conn.close()

    logger.info("=" * 60)
    logger.info("Migration summary")
    logger.info("  Phase F (compress) : %s", compress_result)
    logger.info("  Phase G (webflow)  : %s", upload_result)
    logger.info("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
