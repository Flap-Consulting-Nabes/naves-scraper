"""One-shot back-fill: move MilAnuncios listing URLs from `google-place-id`
to the new `source` field in Webflow CMS, then clear the old slot.

Usage:
    python scripts/migrate_url_to_source.py [--dry-run] [--limit N] [--verbose]

Exit codes:
    0  Clean run, no failures
    1  Partial: at least one item failed during PATCH
    2  Configuration error (missing token / collection id)
"""
import argparse
import asyncio
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from integrations.webflow_client import WebflowClient, COLLECTION_ID, WEBFLOW_TOKEN

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("migrate_url_to_source")

_MILANUNCIOS_URL_RE = re.compile(r"^https?://(www\.)?milanuncios\.com/", re.IGNORECASE)


async def migrate_items(
    client: WebflowClient,
    cms_locale_id: str | None,
    dry_run: bool,
    limit: int | None = None,
) -> dict[str, int]:
    """Walk all CMS items and migrate matching ones.

    Returns counters: {moved, skipped_empty, skipped_non_milanuncios, failed}.
    """
    items = await client.list_items(cms_locale_id=cms_locale_id)
    if limit is not None:
        items = items[:limit]

    moved = 0
    skipped_empty = 0
    skipped_non_milanuncios = 0
    failed = 0

    pending_updates: list[dict] = []

    for item in items:
        item_id = item.get("id", "")
        field_data = item.get("fieldData", {}) or {}
        raw = field_data.get("google-place-id", "")
        value = str(raw).strip() if raw else ""

        if not value:
            skipped_empty += 1
            continue

        if not _MILANUNCIOS_URL_RE.match(value):
            skipped_non_milanuncios += 1
            logger.debug(
                "[MIGRATE] item=%s skipped (non-milanuncios value: %r)",
                item_id, value[:60],
            )
            continue

        logger.info("[MIGRATE] item=%s would move: %s", item_id, value)
        pending_updates.append({
            "id": item_id,
            "fieldData": {"source": value, "google-place-id": ""},
        })
        moved += 1

    if not dry_run and pending_updates:
        result = await client.update_items(pending_updates, cms_locale_id=cms_locale_id)
        if result.get("errors"):
            failed = moved - result.get("updated", 0)
            moved = result.get("updated", 0)
            for err in result["errors"]:
                logger.error("[MIGRATE] update error: %s", err)

    return {
        "moved": moved,
        "skipped_empty": skipped_empty,
        "skipped_non_milanuncios": skipped_non_milanuncios,
        "failed": failed,
    }


async def main_async(args: argparse.Namespace) -> int:
    if not WEBFLOW_TOKEN or not COLLECTION_ID:
        logger.error("WEBFLOW_TOKEN or WEBFLOW_COLLECTION_ID missing in environment")
        return 2

    async with WebflowClient() as client:
        cms_locale_id = await client.resolve_spanish_locale_id()
        summary = await migrate_items(
            client,
            cms_locale_id=cms_locale_id,
            dry_run=args.dry_run,
            limit=args.limit,
        )

    logger.info(
        "[MIGRATE] moved=%d skipped_empty=%d skipped_non_milanuncios=%d failed=%d",
        summary["moved"],
        summary["skipped_empty"],
        summary["skipped_non_milanuncios"],
        summary["failed"],
    )
    return 1 if summary["failed"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be migrated without writing")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process at most N items (for testing)")
    parser.add_argument("--verbose", action="store_true",
                        help="Enable DEBUG logging")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
