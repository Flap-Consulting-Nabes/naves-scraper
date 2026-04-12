"""
Phase F helper for scripts/migrate_images.py — compresses / converts every
image file referenced by `listings.images_local` to the balanced WebP
profile and rewrites the JSON path list in place.

Idempotent:
  - `.webp` already present + size ≤ threshold → skip
  - `.webp` already present + size > threshold → recompress in place
  - `.jpg`/`.png`/etc. present + `.webp` target missing → convert, delete source
  - `.jpg`/`.png`/etc. present + `.webp` target already exists → adopt target, delete source
  - source missing, target present → adopt target silently (prior run)
  - source missing, target missing → log + leave entry alone

Kept in its own module so scripts/migrate_images.py stays under the
300-line limit mandated by CLAUDE.md rule 2.
"""
import json
import logging
import os
import sqlite3
from pathlib import Path

from utils.image_compressor import compress_to_webp

logger = logging.getLogger("migrate_images.phase_f")

_SIZE_THRESHOLD_BYTES = 80 * 1024  # 80 KB — above this, recompress in place


def _derive_webp_path(old_path: Path) -> Path:
    """Return the sibling `.webp` file for `old_path` regardless of its
    original extension. `mungia-2-image-1.jpg` → `mungia-2-image-1.webp`."""
    return old_path.with_suffix(".webp")


def _relative_to_root(path: Path, project_root: Path) -> str:
    try:
        return str(path.relative_to(project_root))
    except ValueError:
        return str(path)


def compress_images(
    conn: sqlite3.Connection,
    project_root: Path,
    dry_run: bool,
    quality: int,
    max_dim: int,
    listing_id_filter: str | None = None,
) -> dict:
    """
    Walk every row with a non-null `images_local`, compress/convert each
    file to WebP, rewrite `images_local` with the new paths.

    When `listing_id_filter` is provided, only that single row is processed
    — used by the `--listing-id` CLI flag for end-to-end testing.

    Returns a summary dict:
      {converted, recompressed, adopted, skipped, failed, rows_updated}
    """
    sql = """
        SELECT listing_id, images_local
        FROM listings
        WHERE images_local IS NOT NULL AND images_local != 'null'
    """
    params: list = []
    if listing_id_filter:
        sql += " AND listing_id = ?"
        params.append(listing_id_filter)
    rows = conn.execute(sql, params).fetchall()
    total = len(rows)
    logger.info("[Phase F] %d listings with images_local", total)

    converted = 0
    recompressed = 0
    adopted = 0
    skipped = 0
    failed = 0
    rows_updated = 0

    for i, row in enumerate(rows, start=1):
        listing_id = row["listing_id"]

        try:
            paths = json.loads(row["images_local"])
        except (json.JSONDecodeError, TypeError):
            logger.warning("[Phase F] %s has malformed images_local — skipping", listing_id)
            continue

        new_paths: list[str] = []
        row_changed = False

        for raw_path in paths:
            result = _process_path(
                Path(raw_path) if Path(raw_path).is_absolute()
                else project_root / raw_path,
                project_root,
                dry_run,
                quality,
                max_dim,
                listing_id,
            )
            if result is None:
                new_paths.append(raw_path)
                skipped += 1
                continue

            action, new_path_str = result
            if action == "converted":
                converted += 1
                row_changed = True
            elif action == "recompressed":
                recompressed += 1
            elif action == "adopted":
                adopted += 1
                row_changed = row_changed or (new_path_str != raw_path)
            elif action == "skipped":
                skipped += 1
            elif action == "failed":
                failed += 1

            new_paths.append(new_path_str)
            if new_path_str != raw_path:
                row_changed = True

        if row_changed:
            rows_updated += 1
            if not dry_run:
                conn.execute(
                    "UPDATE listings SET images_local = ? WHERE listing_id = ?",
                    (json.dumps(new_paths, ensure_ascii=False), listing_id),
                )
                conn.commit()

        if i % 50 == 0:
            logger.info("[Phase F] progress: %d/%d", i, total)

    logger.info(
        "[Phase F] done — converted=%d, recompressed=%d, adopted=%d, "
        "skipped=%d, failed=%d, rows_updated=%d",
        converted, recompressed, adopted, skipped, failed, rows_updated,
    )
    return {
        "converted": converted,
        "recompressed": recompressed,
        "adopted": adopted,
        "skipped": skipped,
        "failed": failed,
        "rows_updated": rows_updated,
    }


def _process_path(
    src_abs: Path,
    project_root: Path,
    dry_run: bool,
    quality: int,
    max_dim: int,
    listing_id: str,
) -> tuple[str, str] | None:
    """
    Process a single image path. Returns `(action, new_path_str)` where
    `action` is one of {converted, recompressed, adopted, skipped, failed},
    or `None` when the source is gone and no target exists (caller keeps
    the original raw_path entry and counts it as skipped).
    """
    target = _derive_webp_path(src_abs)
    target_rel = _relative_to_root(target, project_root)

    # Source already is the webp target
    if src_abs == target and src_abs.exists():
        try:
            size = src_abs.stat().st_size
        except OSError:
            return ("failed", target_rel)
        if size <= _SIZE_THRESHOLD_BYTES:
            return ("skipped", target_rel)
        # Recompress in place
        if dry_run:
            logger.info(
                "[Phase F][dry-run] %s: recompress %s (%d bytes)",
                listing_id, src_abs.name, size,
            )
            return ("recompressed", target_rel)
        try:
            compress_to_webp(src_abs, target, quality=quality, max_dim=max_dim)
            return ("recompressed", target_rel)
        except Exception as e:
            logger.warning(
                "[Phase F] %s: recompress failed for %s: %s",
                listing_id, src_abs, e,
            )
            return ("failed", target_rel)

    # Source is a legacy format (jpg/png/etc.) — convert to webp sibling
    if src_abs.exists():
        if target.exists():
            # Prior run already produced the target — adopt it and drop source
            if not dry_run:
                try:
                    os.remove(src_abs)
                except OSError as e:
                    logger.warning(
                        "[Phase F] %s: could not remove legacy source %s: %s",
                        listing_id, src_abs, e,
                    )
            return ("adopted", target_rel)

        if dry_run:
            logger.info(
                "[Phase F][dry-run] %s: %s → %s",
                listing_id, src_abs.name, target.name,
            )
            return ("converted", target_rel)
        try:
            compress_to_webp(src_abs, target, quality=quality, max_dim=max_dim)
            try:
                os.remove(src_abs)
            except OSError as e:
                logger.warning(
                    "[Phase F] %s: converted but failed to remove source %s: %s",
                    listing_id, src_abs, e,
                )
            return ("converted", target_rel)
        except Exception as e:
            logger.warning(
                "[Phase F] %s: compress failed %s → %s: %s",
                listing_id, src_abs, target, e,
            )
            return ("failed", _relative_to_root(src_abs, project_root))

    # Source missing
    if target.exists():
        return ("adopted", target_rel)

    logger.warning(
        "[Phase F] %s: source and target both missing — leaving entry alone: %s",
        listing_id, src_abs,
    )
    return None
