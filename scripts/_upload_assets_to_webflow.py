"""
Phase G helper for scripts/migrate_images.py — re-uploads every listing's
local `.webp` files to the Webflow Assets CDN and PATCHes the existing
CMS item so `main-image` / `listing-images` / `all-images` point at the
slug-based hosted URLs instead of the UUID-based hashes Webflow assigns
when it re-hosts a remote URL.

**Draft-only constraint:** Phase G only touches Webflow items that are
still in draft state (`isDraft=true`). Already-published items are
skipped entirely so the live blog is never disturbed — the fix is
applied silently in the background and only reaches readers the next
time an editor publishes the affected item.

Idempotent: tracked per row via the `webflow_assets_synced_at` column
(added by db._NEW_COLUMNS and stamped via `db.mark_webflow_assets_synced`).

Starts with an auth probe against `GET /sites/{id}/assets`. If the token
is missing `assets:read` / `assets:write`, the probe raises and the
caller aborts cleanly with exit code 2 — no wasted work.
"""
import asyncio
import json
import logging
import sqlite3
from pathlib import Path

import httpx

from db import mark_webflow_assets_synced
from integrations.webflow_client import COLLECTION_ID, WebflowClient

logger = logging.getLogger("migrate_images.phase_g")

# Only touch these three fields, and only the ones that actually exist in
# the collection schema. Matches the image-field pattern already in
# integrations/webflow_sync.build_field_data.
_IMAGE_FIELD_SLUGS = ("main-image", "listing-images", "all-images")


class AssetsScopeError(RuntimeError):
    """Raised when the auth probe shows the token lacks asset scopes."""


async def _auth_probe(client: WebflowClient) -> None:
    """
    Hit GET /sites/{id}/assets once. A 403 response (or any 4xx really)
    means the token cannot read/write assets — there is no point
    proceeding with Phase G until the user regenerates the token.
    """
    site_id = await client.get_site_id()
    try:
        r = await client._client.get(f"/sites/{site_id}/assets")
    except httpx.HTTPError as e:
        raise AssetsScopeError(f"network error hitting /sites/{{id}}/assets: {e}") from e

    if r.status_code == 403:
        raise AssetsScopeError(
            f"Webflow returned 403 on /sites/{site_id}/assets — "
            "WEBFLOW_TOKEN is missing assets:read / assets:write. "
            "Regenerate the token in the Webflow dashboard with "
            "cms:read, cms:write, assets:read, assets:write, sites:read."
        )
    if r.status_code >= 400:
        raise AssetsScopeError(
            f"Webflow returned HTTP {r.status_code} on /sites/{site_id}/assets: "
            f"{r.text[:200]}"
        )
    logger.info("[Phase G] auth probe OK (HTTP %d)", r.status_code)


async def _fetch_draft_item_ids(client: WebflowClient) -> set[str]:
    """
    Paginate `GET /collections/{id}/items` and return the IDs of every
    Webflow item still marked as draft (`isDraft=true`). Published items
    are intentionally excluded so Phase G never touches the live blog.
    """
    draft_ids: set[str] = set()
    offset = 0
    limit = 100
    while True:
        r = await client._client.get(
            f"/collections/{COLLECTION_ID}/items",
            params={"limit": limit, "offset": offset},
        )
        r.raise_for_status()
        data = r.json()
        items = data.get("items", [])
        if not items:
            break
        for item in items:
            if item.get("isDraft") is True:
                item_id = item.get("id") or item.get("_id") or ""
                if item_id:
                    draft_ids.add(item_id)
        pagination = data.get("pagination") or {}
        total = pagination.get("total", 0)
        offset += len(items)
        if offset >= total or len(items) < limit:
            break
    logger.info(
        "[Phase G] draft filter: %d draft items found in collection",
        len(draft_ids),
    )
    return draft_ids


def _build_image_field_data(
    hosted_urls: list[str],
    alt: str,
    available_slugs: dict[str, str],
) -> dict:
    """
    Build the minimal PATCH payload containing only image fields. Other
    fields remain untouched because Webflow's PATCH endpoint merges
    `fieldData`.
    """
    field_data: dict = {}
    if "main-image" in available_slugs and available_slugs["main-image"] == "Image":
        field_data["main-image"] = {"url": hosted_urls[0], "alt": alt}
    multi = [{"url": u, "alt": alt} for u in hosted_urls]
    for slug in ("listing-images", "all-images"):
        if slug in available_slugs and available_slugs[slug] == "MultiImage":
            field_data[slug] = multi
    return field_data


def _load_local_paths(row_images_local: str, project_root: Path) -> list[Path]:
    """Parse the JSON list and resolve each entry to an absolute path,
    keeping only files that actually exist on disk (up to 10, matching
    the existing sync cap)."""
    try:
        raw = json.loads(row_images_local)
    except (json.JSONDecodeError, TypeError):
        return []
    paths: list[Path] = []
    for entry in raw[:10]:
        p = Path(entry)
        if not p.is_absolute():
            p = project_root / p
        if p.exists():
            paths.append(p)
    return paths


async def upload_and_patch(
    conn: sqlite3.Connection,
    project_root: Path,
    dry_run: bool,
    listing_id_filter: str | None = None,
) -> dict:
    """
    Re-upload every eligible listing's images to Webflow and PATCH the
    CMS item. Eligible = `webflow_item_id` populated (not DUPLICATE) +
    `images_local` populated + `webflow_assets_synced_at` NULL.

    When `listing_id_filter` is provided, only that single row is processed
    — used by the `--listing-id` CLI flag for end-to-end testing.
    """
    sql = """
        SELECT listing_id, title, webflow_item_id, webflow_slug, images_local
        FROM listings
        WHERE webflow_item_id IS NOT NULL
          AND webflow_item_id != ''
          AND webflow_item_id != 'DUPLICATE'
          AND images_local IS NOT NULL
          AND images_local != 'null'
          AND webflow_assets_synced_at IS NULL
    """
    params: list = []
    if listing_id_filter:
        sql += " AND listing_id = ?"
        params.append(listing_id_filter)
    sql += " ORDER BY scraped_at ASC"
    rows = conn.execute(sql, params).fetchall()
    total = len(rows)
    logger.info("[Phase G] %d listings eligible for re-upload", total)

    if total == 0:
        return {
            "uploaded": 0,
            "failed": 0,
            "skipped": 0,
            "skipped_published": 0,
        }

    uploaded = 0
    failed = 0
    skipped = 0
    skipped_published = 0

    async with WebflowClient() as client:
        # Fail fast if the token is wrong
        await _auth_probe(client)

        schema = await client.get_collection_schema()
        available_slugs = {
            f["slug"]: f.get("type") for f in schema.get("fields", [])
        }

        # Fetch draft item IDs once — published items are left untouched
        draft_ids = await _fetch_draft_item_ids(client)

        for i, row in enumerate(rows, start=1):
            listing_id = row["listing_id"]
            webflow_item_id = row["webflow_item_id"]
            alt = row["title"] or row["webflow_slug"] or listing_id

            # Skip published items — Phase G only runs on drafts
            if webflow_item_id not in draft_ids:
                logger.info(
                    "[Phase G] %s: item %s already published, skipping",
                    listing_id, webflow_item_id,
                )
                skipped_published += 1
                continue

            local_paths = _load_local_paths(row["images_local"], project_root)
            if not local_paths:
                logger.warning(
                    "[Phase G] %s: no existing local files, skipping", listing_id,
                )
                skipped += 1
                continue

            if dry_run:
                logger.info(
                    "[Phase G][dry-run] %s → %d files to upload, PATCH item %s",
                    listing_id, len(local_paths), webflow_item_id,
                )
                uploaded += 1
                continue

            hosted_urls: list[str] = []
            for path in local_paths:
                try:
                    url = await client.upload_asset(str(path), path.name)
                    if url:
                        hosted_urls.append(url)
                except Exception as e:
                    logger.warning(
                        "[Phase G] %s: upload failed for %s: %s",
                        listing_id, path.name, e,
                    )

            if not hosted_urls:
                logger.error(
                    "[Phase G] %s: no files uploaded, leaving row unmarked for retry",
                    listing_id,
                )
                failed += 1
                continue

            field_data = _build_image_field_data(hosted_urls, alt, available_slugs)
            if not field_data:
                logger.warning(
                    "[Phase G] %s: collection exposes no image fields — nothing to PATCH",
                    listing_id,
                )
                failed += 1
                continue

            result = await client.update_items([
                {"id": webflow_item_id, "fieldData": field_data}
            ])
            if result["errors"]:
                logger.error(
                    "[Phase G] %s: PATCH failed: %s",
                    listing_id, result["errors"],
                )
                failed += 1
                continue

            mark_webflow_assets_synced(conn, listing_id)
            uploaded += 1
            logger.info(
                "[Phase G] ✓ %s → %d assets hosted, item PATCHed",
                listing_id, len(hosted_urls),
            )

            await asyncio.sleep(0.6)

            if i % 10 == 0:
                logger.info("[Phase G] progress: %d/%d", i, total)

    logger.info(
        "[Phase G] done — uploaded=%d, failed=%d, skipped=%d, "
        "skipped_published=%d",
        uploaded, failed, skipped, skipped_published,
    )
    return {
        "uploaded": uploaded,
        "failed": failed,
        "skipped": skipped,
        "skipped_published": skipped_published,
    }
