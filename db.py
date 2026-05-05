"""
Capa de base de datos SQLite — operaciones CRUD.

El schema y las helpers de migración viven en `db_schema.py` para
mantener este módulo bajo el cap de 300 líneas (Codex review R3).
La función pública `init_db` se queda aquí porque es el entry point
que importa todo el resto del proyecto.
"""
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from db_schema import (
    SCHEMA,
    _ALLOWED_TYPES,
    _NEW_COLUMNS,
    _VALID_COL_RE,
    _safe_add_column,
    migrate_db,
)

# Backward-compat re-exports for callers that import private helpers
# (the test suite touches `_safe_add_column`, `_NEW_COLUMNS`, etc.).
__all__ = [
    "SCHEMA", "_ALLOWED_TYPES", "_NEW_COLUMNS", "_VALID_COL_RE",
    "_safe_add_column", "migrate_db", "init_db",
    "listing_exists", "insert_listing", "update_images_local",
    "update_listing_price", "count_listings", "get_listings_paginated",
    "get_unsynced_listings", "update_webflow_id", "update_webflow_slug",
    "update_canonical_title", "mark_webflow_assets_synced",
    "get_all_listings_for_migration",
]

logger = logging.getLogger(__name__)


def init_db(path: str = "naves.db") -> sqlite3.Connection:
    """Crea la base de datos y las tablas si no existen. Devuelve la conexión."""
    db_path = Path(path)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # escrituras concurrentes más seguras
    # Three writers (scraper subprocess, FastAPI handler, Webflow sync)
    # share this DB. Without a busy timeout, any write collision raises
    # OperationalError: database is locked. 5 s window covers any
    # in-progress commit on the slowest path.
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    conn.commit()
    migrate_db(conn)
    logger.info(f"Base de datos inicializada en {db_path.resolve()}")
    return conn


def listing_exists(conn: sqlite3.Connection, listing_id: str) -> bool:
    """Devuelve True si el anuncio ya está en la base de datos (deduplicación)."""
    row = conn.execute(
        "SELECT 1 FROM listings WHERE listing_id = ?", (listing_id,)
    ).fetchone()
    return row is not None


def insert_listing(conn: sqlite3.Connection, data: dict) -> bool:
    """
    Inserta un anuncio nuevo. Si ya existe (mismo listing_id), lo ignora.
    Devuelve True si fue insertado, False si ya existía.
    """
    # Serializar campos JSON
    photos = data.get("photos")
    if isinstance(photos, list):
        photos = json.dumps(photos, ensure_ascii=False)

    features = data.get("features")
    if isinstance(features, list):
        features = json.dumps(features, ensure_ascii=False)

    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO listings (
                listing_id, url, reference,
                title, description,
                price, price_numeric, price_per_m2,
                surface_m2, rooms, bathrooms, floor, condition, energy_certificate, features,
                ad_type, property_type,
                location, province, address, zipcode, latitude, longitude,
                seller_type, seller_name, seller_id, seller_url, phone, phone2,
                photos,
                published_at, updated_at, raw_html,
                webflow_slug, original_title
            ) VALUES (
                :listing_id, :url, :reference,
                :title, :description,
                :price, :price_numeric, :price_per_m2,
                :surface_m2, :rooms, :bathrooms, :floor, :condition, :energy_certificate, :features,
                :ad_type, :property_type,
                :location, :province, :address, :zipcode, :latitude, :longitude,
                :seller_type, :seller_name, :seller_id, :seller_url, :phone, :phone2,
                :photos,
                :published_at, :updated_at, :raw_html,
                :webflow_slug, :original_title
            )
            """,
            {
                "listing_id":         data.get("listing_id"),
                "url":                data.get("url"),
                "reference":          data.get("reference"),
                "title":              data.get("title"),
                "description":        data.get("description"),
                "price":              data.get("price"),
                "price_numeric":      data.get("price_numeric"),
                "price_per_m2":       data.get("price_per_m2"),
                "surface_m2":         data.get("surface_m2"),
                "rooms":              data.get("rooms"),
                "bathrooms":          data.get("bathrooms"),
                "floor":              data.get("floor"),
                "condition":          data.get("condition"),
                "energy_certificate": data.get("energy_certificate"),
                "features":           features,
                "ad_type":            data.get("ad_type"),
                "property_type":      data.get("property_type"),
                "location":           data.get("location"),
                "province":           data.get("province"),
                "address":            data.get("address"),
                "zipcode":            data.get("zipcode"),
                "latitude":           data.get("latitude"),
                "longitude":          data.get("longitude"),
                "seller_type":        data.get("seller_type"),
                "seller_name":        data.get("seller_name"),
                "seller_id":          data.get("seller_id"),
                "seller_url":         data.get("seller_url"),
                "phone":              data.get("phone"),
                "phone2":             data.get("phone2"),
                "photos":             photos,
                "published_at":       data.get("published_at"),
                "updated_at":         data.get("updated_at"),
                "raw_html":           data.get("raw_html"),
                "webflow_slug":       data.get("webflow_slug"),
                "original_title":     data.get("original_title"),
            },
        )
        conn.commit()
        inserted = conn.execute("SELECT changes()").fetchone()[0] > 0
        if inserted:
            logger.info(f"[DB] Insertado: {data.get('listing_id')} — {data.get('title', '')[:60]}")
        else:
            logger.debug(f"[DB] Duplicado ignorado: {data.get('listing_id')}")
        return inserted
    except sqlite3.Error as e:
        logger.error(f"[DB] Error insertando {data.get('listing_id')}: {e}")
        conn.rollback()
        return False


def update_images_local(conn: sqlite3.Connection, listing_id: str, local_paths: list[str]) -> None:
    """Actualiza los paths locales de las imágenes descargadas."""
    conn.execute(
        "UPDATE listings SET images_local = ? WHERE listing_id = ?",
        (json.dumps(local_paths, ensure_ascii=False), listing_id),
    )
    conn.commit()
    logger.debug(f"[DB] images_local actualizado para {listing_id}: {len(local_paths)} imágenes")


def update_listing_price(conn: sqlite3.Connection, listing_id: str, price: str) -> None:
    """Actualiza el precio de un anuncio existente si ha cambiado."""
    conn.execute(
        "UPDATE listings SET price = ?, updated_at = ? WHERE listing_id = ?",
        (price, datetime.now(timezone.utc).isoformat(), listing_id),
    )
    conn.commit()
    logger.info(f"[DB] Precio actualizado para {listing_id}: {price}")


def count_listings(conn: sqlite3.Connection) -> int:
    """Devuelve el total de anuncios en la base de datos."""
    return conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]


def get_listings_paginated(
    conn: sqlite3.Connection,
    page: int = 1,
    page_size: int = 50,
    province: str | None = None,
    min_surface: float | None = None,
    max_price: float | None = None,
    sort_by: str = "scraped_at",
    sort_dir: str = "desc",
) -> tuple[list[dict], int]:
    """Devuelve (filas, total) con filtros opcionales. Excluye raw_html."""
    allowed_sort = {"scraped_at", "price_numeric", "surface_m2", "published_at"}
    if sort_by not in allowed_sort:
        sort_by = "scraped_at"
    sort_dir = "DESC" if sort_dir.lower() == "desc" else "ASC"

    where_clauses = []
    params: list = []
    if province:
        where_clauses.append("province LIKE ?")
        params.append(f"%{province}%")
    if min_surface is not None:
        where_clauses.append("surface_m2 >= ?")
        params.append(min_surface)
    if max_price is not None:
        where_clauses.append("price_numeric <= ?")
        params.append(max_price)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    total = conn.execute(
        f"SELECT COUNT(*) FROM listings {where_sql}", params
    ).fetchone()[0]

    offset = (page - 1) * page_size
    rows = conn.execute(
        f"""
        SELECT listing_id, url, title, description, price, price_numeric, price_per_m2,
               surface_m2, rooms, bathrooms, floor, condition, energy_certificate, features,
               ad_type, property_type, location, province, address, zipcode,
               latitude, longitude,
               seller_type, seller_name, seller_id, seller_url, phone, phone2,
               photos, images_local, published_at, updated_at, scraped_at,
               webflow_item_id, webflow_synced_at
        FROM listings {where_sql}
        ORDER BY {sort_by} {sort_dir}
        LIMIT ? OFFSET ?
        """,
        params + [page_size, offset],
    ).fetchall()

    return [dict(r) for r in rows], total


def get_unsynced_listings(conn: sqlite3.Connection) -> list[dict]:
    """Devuelve anuncios que aún no han sido enviados a Webflow."""
    rows = conn.execute(
        """
        SELECT listing_id, url, title, original_title, description,
               price, price_numeric, price_per_m2,
               surface_m2, rooms, bathrooms, floor, condition, energy_certificate, features,
               ad_type, property_type, location, province, address, zipcode,
               latitude, longitude,
               seller_type, seller_name, phone, phone2,
               photos, images_local, published_at, updated_at, webflow_slug
        FROM listings
        WHERE webflow_item_id IS NULL
        ORDER BY scraped_at DESC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def update_webflow_id(
    conn: sqlite3.Connection, listing_id: str, webflow_item_id: str
) -> None:
    """Marca un anuncio como sincronizado con Webflow."""
    conn.execute(
        "UPDATE listings SET webflow_item_id = ?, webflow_synced_at = ? WHERE listing_id = ?",
        (webflow_item_id, datetime.now(timezone.utc).isoformat(), listing_id),
    )
    conn.commit()
    logger.debug(f"[DB] Webflow ID guardado para {listing_id}: {webflow_item_id}")


def update_webflow_slug(
    conn: sqlite3.Connection, listing_id: str, webflow_slug: str
) -> None:
    """Stores the unique title-based slug for a listing."""
    conn.execute(
        "UPDATE listings SET webflow_slug = ? WHERE listing_id = ?",
        (webflow_slug, listing_id),
    )
    conn.commit()
    logger.debug(f"[DB] webflow_slug guardado para {listing_id}: {webflow_slug}")


def update_canonical_title(
    conn: sqlite3.Connection,
    listing_id: str,
    new_title: str,
    new_slug: str,
    original_title: str | None,
) -> None:
    """Replace title/slug with canonical values; preserve original_title when first set.

    Iteración 2026-05 (Tarea 2). The COALESCE guarantees we don't overwrite
    a previously stored original_title on a re-run.
    """
    conn.execute(
        """
        UPDATE listings
        SET title = ?,
            webflow_slug = ?,
            original_title = COALESCE(original_title, ?)
        WHERE listing_id = ?
        """,
        (new_title, new_slug, original_title, listing_id),
    )
    conn.commit()
    logger.debug(
        "[DB] canonical title applied for %s: %r → %r (slug=%s)",
        listing_id, original_title, new_title, new_slug,
    )


def mark_webflow_assets_synced(
    conn: sqlite3.Connection, listing_id: str
) -> None:
    """
    Stamp a listing as having had its images re-uploaded to Webflow's
    Assets CDN (used by scripts/migrate_images.py Phase G to make the
    one-shot re-upload idempotent across re-runs).
    """
    conn.execute(
        "UPDATE listings SET webflow_assets_synced_at = ? WHERE listing_id = ?",
        (datetime.now(timezone.utc).isoformat(), listing_id),
    )
    conn.commit()
    logger.debug(f"[DB] webflow_assets_synced_at stamped for {listing_id}")


def get_all_listings_for_migration(conn: sqlite3.Connection) -> list[dict]:
    """
    Returns every listing with only the columns needed by scripts/migrate_slugs.py.
    Ordered by scraped_at ASC so the oldest row keeps the bare slug and newer
    collisions get the `-2`, `-3`... suffix.
    """
    rows = conn.execute(
        """
        SELECT listing_id, title, webflow_slug, webflow_item_id, images_local
        FROM listings
        ORDER BY scraped_at ASC
        """
    ).fetchall()
    return [dict(r) for r in rows]
