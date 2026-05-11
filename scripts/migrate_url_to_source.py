"""One-shot back-fill: move MilAnuncios listing URLs from `google-place-id`
to the new `source` field in Webflow CMS, then clear the old slot.

Usage:
    python scripts/migrate_url_to_source.py [--dry-run] [--limit N]
                                            [--since-days N] [--verbose]

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
from datetime import datetime, timedelta, timezone
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


def _parse_iso(ts: str | None) -> datetime | None:
    """Parse Webflow's `lastUpdated` / `createdOn` ISO 8601 strings.

    Webflow returns trailing-Z UTC timestamps like `2026-05-11T10:42:26.906Z`.
    Python's fromisoformat handles the offset form, so we replace `Z` first.
    """
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


async def migrate_items(
    client: WebflowClient,
    cms_locale_id: str | None,
    dry_run: bool,
    limit: int | None = None,
    since: datetime | None = None,
) -> dict[str, int]:
    """Walk all CMS items and migrate matching ones.

    When `since` is set, items whose `lastUpdated` is older than that
    timestamp are skipped (counted under `skipped_too_old`).

    Returns counters: {moved, skipped_empty, skipped_non_milanuncios,
    skipped_too_old, failed}.
    """
    items = await client.list_items(cms_locale_id=cms_locale_id)
    if limit is not None:
        items = items[:limit]

    moved = 0
    skipped_empty = 0
    skipped_non_milanuncios = 0
    skipped_too_old = 0
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

        if since is not None:
            last_updated = _parse_iso(item.get("lastUpdated") or item.get("createdOn"))
            if last_updated is None or last_updated < since:
                skipped_too_old += 1
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
        "skipped_too_old": skipped_too_old,
        "failed": failed,
    }


async def main_async(args: argparse.Namespace) -> int:
    if not WEBFLOW_TOKEN or not COLLECTION_ID:
        logger.error("WEBFLOW_TOKEN or WEBFLOW_COLLECTION_ID missing in environment")
        return 2

    since: datetime | None = None
    if args.since_days is not None:
        since = datetime.now(timezone.utc) - timedelta(days=args.since_days)
        logger.info(
            "[MIGRATE] Filter: only items with lastUpdated >= %s "
            "(last %d days)", since.isoformat(), args.since_days,
        )

    async with WebflowClient() as client:
        cms_locale_id = await client.resolve_spanish_locale_id()
        summary = await migrate_items(
            client,
            cms_locale_id=cms_locale_id,
            dry_run=args.dry_run,
            limit=args.limit,
            since=since,
        )

    logger.info(
        "[MIGRATE] moved=%d skipped_empty=%d skipped_non_milanuncios=%d "
        "skipped_too_old=%d failed=%d",
        summary["moved"],
        summary["skipped_empty"],
        summary["skipped_non_milanuncios"],
        summary["skipped_too_old"],
        summary["failed"],
    )
    return 1 if summary["failed"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be migrated without writing")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process at most N items (for testing)")
    parser.add_argument("--since-days", type=int, default=None,
                        help="Only migrate items updated in the last N days "
                             "(filters on Webflow's lastUpdated timestamp)")
    parser.add_argument("--verbose", action="store_true",
                        help="Enable DEBUG logging")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
