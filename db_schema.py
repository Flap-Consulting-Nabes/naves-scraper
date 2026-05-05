"""Schema + migration helpers for the SQLite listings table.

Codex review R3: extracted from `db.py` so the CRUD module stays under
the 300-line cap. Public surface is unchanged — `db.py` re-exports
`init_db`, which is what every caller imports.
"""
from __future__ import annotations

import logging
import re
import sqlite3

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id         TEXT UNIQUE NOT NULL,
    url                TEXT NOT NULL,
    reference          TEXT,

    title              TEXT,
    description        TEXT,

    price              TEXT,
    price_numeric      REAL,
    price_per_m2       REAL,

    surface_m2         REAL,
    rooms              INTEGER,
    bathrooms          INTEGER,
    floor              TEXT,
    condition          TEXT,
    energy_certificate TEXT,
    features           TEXT,

    ad_type            TEXT,
    property_type      TEXT,

    location           TEXT,
    province           TEXT,
    address            TEXT,
    zipcode            TEXT,
    latitude           REAL,
    longitude          REAL,
    original_title     TEXT,

    seller_type        TEXT,
    seller_name        TEXT,
    seller_id          TEXT,
    seller_url         TEXT,
    phone              TEXT,
    phone2             TEXT,

    photos             TEXT,
    images_local       TEXT,

    published_at       TEXT,
    updated_at         TEXT,
    scraped_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    raw_html           TEXT,

    webflow_item_id    TEXT,
    webflow_synced_at  TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_listing_id  ON listings(listing_id);
CREATE INDEX IF NOT EXISTS idx_scraped_at  ON listings(scraped_at);
CREATE INDEX IF NOT EXISTS idx_surface     ON listings(surface_m2);
CREATE INDEX IF NOT EXISTS idx_province    ON listings(province);
"""

# Columnas nuevas respecto al schema inicial (para migración de BD existente)
_NEW_COLUMNS = [
    ("reference",          "TEXT"),
    ("price_numeric",      "REAL"),
    ("price_per_m2",       "REAL"),
    ("ad_type",            "TEXT"),
    ("property_type",      "TEXT"),
    ("condition",          "TEXT"),
    ("energy_certificate", "TEXT"),
    ("features",           "TEXT"),
    ("bathrooms",          "INTEGER"),
    ("address",            "TEXT"),
    ("zipcode",            "TEXT"),
    ("phone2",             "TEXT"),
    ("seller_id",          "TEXT"),
    ("seller_url",         "TEXT"),
    ("images_local",            "TEXT"),
    ("webflow_item_id",         "TEXT"),
    ("webflow_synced_at",       "TIMESTAMP"),
    ("webflow_slug",            "TEXT"),
    ("webflow_assets_synced_at", "TIMESTAMP"),
    ("latitude",                 "REAL"),
    ("longitude",                "REAL"),
    ("original_title",           "TEXT"),
]


_VALID_COL_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_ALLOWED_TYPES = {"TEXT", "REAL", "INTEGER", "TIMESTAMP", "BLOB"}


def _safe_add_column(conn: sqlite3.Connection, col: str, typ: str) -> None:
    """Validate column name/type before issuing ALTER TABLE (anti-injection)."""
    if not _VALID_COL_RE.match(col):
        raise ValueError(f"Invalid column name: {col!r}")
    if typ.upper() not in _ALLOWED_TYPES:
        raise ValueError(f"Invalid column type: {typ!r}")
    conn.execute(f"ALTER TABLE listings ADD COLUMN {col} {typ}")


def migrate_db(conn: sqlite3.Connection) -> None:
    """Add columns introduced after the initial schema without losing data.

    Idempotent — only adds columns that don't already exist. Also creates
    indices for columns added late so they are guaranteed to exist on
    every fresh DB.
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(listings)")}
    added = []
    for col, typ in _NEW_COLUMNS:
        if col not in existing:
            _safe_add_column(conn, col, typ)
            added.append(col)
    if added:
        conn.commit()
        logger.info(f"[DB] Migración: columnas añadidas → {added}")

    # Índices para columnas nuevas (seguros de crear después de migración)
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_price           ON listings(price_numeric);
        CREATE INDEX IF NOT EXISTS idx_ad_type         ON listings(ad_type);
        CREATE INDEX IF NOT EXISTS idx_webflow_item_id ON listings(webflow_item_id);
        CREATE INDEX IF NOT EXISTS idx_webflow_slug    ON listings(webflow_slug);
    """)
    conn.commit()
