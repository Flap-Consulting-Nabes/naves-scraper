"""
Title-based slug generation with collision handling.

Used by scraper_engine (at scrape time) and the migration script to produce a
single, stable slug per listing. The slug is reused as:
  - the Webflow CMS page slug
  - the local image filename prefix under images/{listing_id}/

Collision rule: the first duplicate gets `-2`, the next `-3`, and so on.
An empty or unparseable title falls back to `nave-{listing_id}`, which is
always unique because `listings.listing_id` is unique.
"""
import re
import sqlite3
import unicodedata


def slugify_title(title: str | None, listing_id: str, max_length: int = 75) -> str:
    """
    Convert a listing title into a URL-safe slug.

    Truncated to `max_length` characters so a numeric collision suffix
    (e.g. `-123`) can be appended without exceeding typical CMS slug limits.
    """
    text = title.strip() if title else ""
    if not text:
        return f"nave-{listing_id}"

    # Transliterate unicode accents (á→a, ñ→n, ²→'', etc.)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text)
    text = text.strip("-")

    if not text:
        return f"nave-{listing_id}"

    return text[:max_length].rstrip("-")


def generate_unique_slug(
    conn: sqlite3.Connection,
    title: str | None,
    listing_id: str,
    exclude_listing_id: str | None = None,
) -> str:
    """
    Compute a unique slug for a listing, appending a numeric suffix when
    another row already owns the base slug.

    `exclude_listing_id` lets the migration re-compute a row's own slug
    without treating the row's existing value as a collision.
    """
    base = slugify_title(title, listing_id)

    # Find any existing slugs that match `base` or `base-<n>`.
    rows = conn.execute(
        """
        SELECT webflow_slug FROM listings
        WHERE webflow_slug IS NOT NULL
          AND (webflow_slug = ? OR webflow_slug LIKE ? || '-%')
          AND (? IS NULL OR listing_id != ?)
        """,
        (base, base, exclude_listing_id, exclude_listing_id),
    ).fetchall()

    if not rows:
        return base

    # Collect numeric suffixes from collisions: `base`, `base-2`, `base-3`...
    suffix_re = re.compile(rf"^{re.escape(base)}(?:-(\d+))?$")
    max_suffix = 1  # treat `base` itself as implicit suffix 1
    for row in rows:
        slug = row[0] if not isinstance(row, sqlite3.Row) else row["webflow_slug"]
        if not slug:
            continue
        match = suffix_re.match(slug)
        if not match:
            continue
        if match.group(1):
            try:
                max_suffix = max(max_suffix, int(match.group(1)))
            except ValueError:
                continue

    return f"{base}-{max_suffix + 1}"
