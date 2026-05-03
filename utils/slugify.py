"""
Title-based slug generation with collision handling.

Used by scraper_engine (at scrape time) and the migration script to produce a
single, stable slug per listing. The slug is reused as:
  - the Webflow CMS page slug
  - the local image filename prefix under images/{listing_id}/

Collision rule: the first duplicate gets `-2`, the next `-3`, and so on.
An empty or unparseable title falls back to `nave-{listing_id}`, which is
always unique because `listings.listing_id` is unique.

Iteración 2026-05 (Tarea 2):
The canonical title format requested by the client is
`Nave industrial en {venta|alquiler} en {Name}` where `{Name}` is derived
with `extract_warehouse_name` (location-first, address-with-street as
fallback for extra specificity). `build_canonical_title` produces the
title; `slugify_title` then turns it into the slug.
"""
import logging
import re
import sqlite3
import unicodedata

logger = logging.getLogger(__name__)

_STREET_KEYWORDS_RE = re.compile(
    r"\b(calle|c/|avda|avenida|polígono|poligono|carretera|paseo|plaza|"
    r"glorieta|ronda|camino|via|vía)\b",
    re.IGNORECASE,
)
_STARTS_WITH_CP_RE = re.compile(r"^\d{4,5}")


def extract_warehouse_name(data: dict) -> str | None:
    """Return the {Name} component for the canonical title.

    Resolution order:
      1. `location` (city/polígono of the property — comes from the ad JSON)
      2. `address` extended with the street fragment when it actually
         contains a street keyword and does not start with a postal code.
      3. None if neither is usable (caller should keep the original title).
    """
    address = (data.get("address") or "").strip()
    location = (data.get("location") or "").strip()

    if location:
        return location

    if address and not _STARTS_WITH_CP_RE.match(address) and _STREET_KEYWORDS_RE.search(address):
        # Take only the street fragment up to the first comma/CP boundary.
        street_part = re.split(r",\s*\d{4,5}|,\s*", address, maxsplit=1)[0]
        street_part = street_part.strip()
        if len(street_part) > 3:
            return street_part

    return None


def build_canonical_title(ad_type: str | None, name: str | None) -> str | None:
    """Return `Nave industrial en {venta|alquiler} en {Name}` or None.

    Returns None when either input is missing so the caller can fall back
    to the original scraped title rather than producing nonsense.
    """
    if not ad_type or not name:
        return None
    if ad_type not in ("venta", "alquiler"):
        return None
    return f"Nave industrial en {ad_type} en {name}"


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
