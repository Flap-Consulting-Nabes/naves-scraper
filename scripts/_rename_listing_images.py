"""
Phase C helper for scripts/migrate_slugs.py — renames image files on disk
to match the new `{webflow_slug}-image-{i}.{ext}` naming convention and
rewrites `listings.images_local` accordingly.

Kept in its own module so migrate_slugs.py stays under the 300-line limit
mandated by CLAUDE.md rule 2.
"""
import json
import logging
import os
import sqlite3
from pathlib import Path

logger = logging.getLogger("migrate_slugs.phase_c")

_IMAGE_EXTS = ("jpg", "jpeg", "png", "webp", "gif")


def _derive_new_path(old_path: Path, slug: str, index: int) -> Path:
    ext = old_path.suffix.lstrip(".").lower() or "jpg"
    if ext not in _IMAGE_EXTS:
        ext = "jpg"
    return old_path.parent / f"{slug}-image-{index}.{ext}"


def _relative_to_root(path: Path, project_root: Path) -> str:
    try:
        return str(path.relative_to(project_root))
    except ValueError:
        return str(path)


def rename_images(
    conn: sqlite3.Connection, project_root: Path, dry_run: bool
) -> dict:
    """
    Rename every image file referenced by `listings.images_local` to
    `{webflow_slug}-image-{i}.{ext}` and update the DB row.

    Idempotent: skips files that already match the target name, re-uses
    pre-existing targets from a prior run, and leaves the DB entry alone
    when the source file is missing.
    """
    rows = conn.execute(
        """
        SELECT listing_id, webflow_slug, images_local
        FROM listings
        WHERE images_local IS NOT NULL AND images_local != 'null'
        """
    ).fetchall()
    total = len(rows)
    logger.info("[Phase C] %d listings with images_local", total)

    renamed_files = 0
    skipped_files = 0
    updated_rows = 0

    for i, row in enumerate(rows, start=1):
        listing_id = row["listing_id"]
        slug = row["webflow_slug"]
        if not slug:
            logger.warning(
                "[Phase C] %s has images_local but no webflow_slug — run Phase B first",
                listing_id,
            )
            continue

        try:
            paths = json.loads(row["images_local"])
        except (json.JSONDecodeError, TypeError):
            logger.warning("[Phase C] %s has malformed images_local — skipping", listing_id)
            continue

        new_paths: list[str] = []
        row_changed = False

        for idx, raw_path in enumerate(paths, start=1):
            old_path = Path(raw_path)
            if not old_path.is_absolute():
                old_path = project_root / old_path

            new_path = _derive_new_path(old_path, slug, idx)

            if new_path == old_path:
                new_paths.append(raw_path)
                continue

            if not old_path.exists():
                if new_path.exists():
                    new_paths.append(_relative_to_root(new_path, project_root))
                    row_changed = True
                    continue
                logger.warning(
                    "[Phase C] %s missing source file, leaving entry: %s",
                    listing_id, raw_path,
                )
                new_paths.append(raw_path)
                skipped_files += 1
                continue

            if new_path.exists():
                logger.info("[Phase C] target exists, adopting %s", new_path)
                new_paths.append(_relative_to_root(new_path, project_root))
                row_changed = True
                continue

            if dry_run:
                logger.info(
                    "[Phase C][dry-run] %s: %s → %s",
                    listing_id, old_path.name, new_path.name,
                )
            else:
                try:
                    os.rename(old_path, new_path)
                except OSError as e:
                    logger.warning(
                        "[Phase C] rename failed %s → %s: %s",
                        old_path, new_path, e,
                    )
                    new_paths.append(raw_path)
                    skipped_files += 1
                    continue

            new_paths.append(_relative_to_root(new_path, project_root))
            renamed_files += 1
            row_changed = True

        if row_changed:
            updated_rows += 1
            if not dry_run:
                conn.execute(
                    "UPDATE listings SET images_local = ? WHERE listing_id = ?",
                    (json.dumps(new_paths, ensure_ascii=False), listing_id),
                )
                conn.commit()

        if i % 50 == 0:
            logger.info("[Phase C] progress: %d/%d", i, total)

    logger.info(
        "[Phase C] done — renamed=%d, skipped=%d, rows_updated=%d",
        renamed_files, skipped_files, updated_rows,
    )
    return {
        "renamed": renamed_files,
        "skipped": skipped_files,
        "rows_updated": updated_rows,
    }
