"""
Image downloader for scraped listings.

Extracted from scraper_engine.py so the main orchestrator stays lean. The
download_images() entry point takes the final unique slug (computed upstream
via utils.slugify.generate_unique_slug) and uses it directly as the filename
prefix: {slug}-image-{i}.webp.

Since 2026-04 every photo is compressed to WebP on the way in via
utils.image_compressor.compress_to_webp (balanced profile: q=80, max 1200px).
Source bytes are never written to disk — only the compressed output lands
in `images/{listing_id}/`.
"""
import asyncio
import logging
import os
import sqlite3
from pathlib import Path

import requests

from db import update_images_local
from utils.image_compressor import compress_to_webp

logger = logging.getLogger(__name__)

IMAGES_DIR = os.getenv("IMAGES_DIR", "images")


def _fetch_and_compress(url: str, dest: Path) -> bool:
    """
    Download the raw bytes from `url` and write them to `dest` as a WebP
    compressed via `compress_to_webp`. Runs entirely synchronously — call
    via `asyncio.to_thread` from the async entry point.
    """
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        compress_to_webp(resp.content, dest)
        return True
    except Exception as e:
        logger.warning(f"[IMG] Error descargando/comprimiendo {url}: {e}")
        return False


async def download_images(
    conn: sqlite3.Connection,
    listing_id: str,
    photo_urls: list,
    slug: str,
) -> None:
    """
    Download all photos for a listing, compress to WebP, and record the
    local paths in the DB.

    Files are written to `images/{listing_id}/{slug}-image-{i}.webp`. The
    caller must pre-compute `slug` (the final unique slug stored alongside
    the listing) so the filenames stay in sync with the Webflow page slug.
    """
    if not photo_urls:
        return

    folder = Path(IMAGES_DIR) / listing_id
    folder.mkdir(parents=True, exist_ok=True)

    local_paths: list[str] = []
    for i, url in enumerate(photo_urls, start=1):
        dest = folder / f"{slug}-image-{i}.webp"
        ok = await asyncio.to_thread(_fetch_and_compress, url, dest)
        if ok:
            local_paths.append(str(dest))

    if local_paths:
        update_images_local(conn, listing_id, local_paths)
        logger.info(
            f"[IMG] {listing_id}: {len(local_paths)}/{len(photo_urls)} "
            f"imágenes descargadas → {folder}"
        )
