"""
Orquestador de sincronización DB → Webflow CMS.

Estrategia de mapeo de campos:
  - Al iniciar sync, descarga el schema de la colección Webflow
  - Intenta mapear campos de la DB usando listas de slugs candidatos
  - Loguea los campos que no se pudieron mapear (no es error fatal)
  - Sube imágenes locales al CDN de Webflow antes de crear cada item
  - Crea items como draft con isDraft=true
  - Deduplicación: solo procesa listings con webflow_item_id IS NULL
"""
import asyncio
import json
import logging
import os
import re
import sqlite3
from pathlib import Path

import httpx
from dotenv import load_dotenv

from db import get_unsynced_listings, init_db, update_webflow_id
from integrations.cloudinary_client import delete_images as cloudinary_delete_images
from integrations.webflow_client import WebflowClient
from integrations.webflow_image_uploader import upload_listing_images
from utils.description_formatter import format_description_html
from utils.price_formatter import format_price_display

load_dotenv()
logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "naves.db")
PROJECT_ROOT = Path(__file__).parent.parent

# ── Mapeo de campos DB → slugs Webflow ───────────────────────────────────────
# Para cada campo de la DB, se prueba una lista de slugs posibles (en orden de prioridad).
# El primer slug que coincida con los campos reales de la colección se usa.

FIELD_MAP_PATTERNS: dict[str, list[str]] = {
    "title":            ["name", "title", "nombre", "titulo", "titulo-anuncio"],
    "description":      ["description", "descripcion", "descripción", "contenido", "funeral-home-biography"],
    "price_numeric":    ["new-sale-price", "price", "precio", "price-2", "precio-venta", "precio-alquiler"],
    "price_per_m2":     ["new-price-sm2-month", "price-per-m2", "precio-m2", "precio-por-metro", "precio-metro"],
    "surface_m2":       ["squared-meters", "superficie", "surface", "area", "metros", "m2", "superficie-m2"],
    "rooms":            ["rooms", "habitaciones", "despachos"],
    "bathrooms":        ["bathrooms", "banos", "baños", "aseos"],
    "floor":            ["floor", "planta", "piso"],
    "condition":        ["condition", "estado", "estado-inmueble"],
    "energy_certificate": ["energy-certificate", "certificado-energetico", "eficiencia"],
    "ad_type":          ["ad-type", "tipo-operacion", "tipo-anuncio", "operacion"],
    "property_type":    ["property-type", "tipo-inmueble", "tipo-propiedad", "categoria"],
    "location":         ["location", "ubicacion", "ubicación", "localidad", "municipio", "ciudad"],
    "province":         ["province", "provincia", "comunidad"],
    "address":          ["full-address", "address", "direccion", "dirección", "calle"],
    "zipcode":          ["zipcode", "zip", "codigo-postal", "cp"],
    "latitude":         ["latitude", "lat"],
    "longitude":        ["longitude", "lng", "lon"],
    "seller_type":      ["seller-type", "tipo-vendedor", "tipo-anunciante"],
    "seller_name":      ["contact-name", "seller", "vendedor", "agencia", "anunciante", "empresa"],
    "phone":            ["contact-number", "phone", "telefono", "teléfono", "contacto"],
    # New items write the MilAnuncios listing URL to `source` (the slug
    # Benedict created 2026-05-09). `google-place-id` is kept as a
    # transitional fallback for items not yet moved by
    # scripts/migrate_url_to_source.py. Once the back-fill is verified in
    # prod, drop `google-place-id` from this list (see spec
    # docs/superpowers/specs/2026-05-10-source-url-migration-design.md).
    "url":              ["source", "source-url", "google-place-id", "url", "link", "enlace", "url-origen"],
    "published_at":     ["published-date", "fecha-publicacion", "fecha-anuncio", "publish-date"],
}


# Match the trailing numeric ID in a MilAnuncios listing URL:
# https://www.milanuncios.com/.../slug-{ID}.htm
_LISTING_ID_RE = re.compile(r"-(\d+)\.htm$")


def _extract_listing_id(url: str | None) -> str | None:
    """Extract the trailing numeric listing ID from a MilAnuncios URL.

    Returns None for empty input or URLs without a trailing `-{digits}.htm`.
    Used to key the Webflow dedup index by the same invariant identifier
    the DB uses (`listings.listing_id`).
    """
    if not url:
        return None
    m = _LISTING_ID_RE.search(url)
    return m.group(1) if m else None


def resolve_field_mapping(collection_schema: dict) -> dict[str, str]:
    """
    Compara los slugs candidatos con los slugs reales de la colección.
    Retorna {db_column: webflow_slug} para los campos que se pudieron mapear.
    """
    available: dict[str, str] = {}
    for field in collection_schema.get("fields", []):
        slug = field.get("slug", "")
        if slug:
            available[slug.lower()] = slug

    resolved: dict[str, str] = {}
    unmatched: list[str] = []

    for db_field, candidates in FIELD_MAP_PATTERNS.items():
        matched = False
        for candidate in candidates:
            if candidate.lower() in available:
                resolved[db_field] = available[candidate.lower()]
                matched = True
                break
        if not matched:
            unmatched.append(db_field)

    if unmatched:
        # WARNING (not INFO) so a schema rename that drops a critical
        # field (e.g. `new-sale-price` → `sale-price`) is visible in the
        # default log view.
        logger.warning(
            "[Webflow] Campos DB sin mapeo en la colección (se omitirán): %s", unmatched
        )
    logger.info("[Webflow] Campos mapeados (%d): %s", len(resolved), list(resolved.values()))
    return resolved


def _coerce_field_value(
    db_field: str,
    wf_slug: str,
    value,
    field_types: dict[str, str],
) -> object | None:
    """Coerce a single DB value into the type Webflow expects for the
    target slug. Returns None when the value should be skipped."""
    if value is None:
        return None
    ftype = field_types.get(wf_slug, "PlainText")
    if ftype == "Number":
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if ftype in ("Date", "DateTime"):
        if isinstance(value, str) and value:
            return value if "T" in value else value + "T00:00:00.000Z"
        return None
    if ftype == "RichText" and db_field == "description":
        # Iteración 2026-05, Tarea 4: convert raw text to HTML so the
        # frontend renders paragraphs and bullet lists correctly.
        return format_description_html(str(value)) or None
    return str(value)


def _route_price_to_field(
    field_data: dict,
    row: dict,
    available_slugs: set[str],
) -> None:
    """Override the generic price serialisation with the locale-aware
    display string and route it to the correct slot per ad_type:
      venta            → new-sale-price ("199.000 €")
      alquiler / dual  → new-price-sm2-month ("1.19€/m²" or "1.500 €/mes")

    Codex review R2: extracted from build_field_data so price routing is
    independently testable. Mutates `field_data` in place.
    """
    ad_type = row.get("ad_type")
    formatted = format_price_display(
        ad_type, row.get("price_numeric"), row.get("price_per_m2"),
    )
    if formatted is None:
        return

    if ad_type == "venta" and "new-sale-price" in available_slugs:
        field_data["new-sale-price"] = formatted
        field_data.pop("new-price-sm2-month", None)
    elif ad_type in ("alquiler", "venta_alquiler"):
        # Dual offerings reuse the alquiler routing: the price extracted
        # from MilAnuncios is the rental rate, and the sale slot stays
        # empty (the listing rarely quotes both prices). The title
        # already advertises both modalities via build_canonical_title.
        if "new-price-sm2-month" in available_slugs:
            field_data["new-price-sm2-month"] = formatted
        elif "new-sale-price" in available_slugs:
            field_data["new-sale-price"] = formatted
        if "new-price-sm2-month" in available_slugs:
            field_data.pop("new-sale-price", None)


def _assign_image_fields(
    field_data: dict,
    image_urls: list[str],
    collection_fields: list[dict],
    alt: str,
) -> None:
    """Dedup `image_urls` (preserving order) and split across the four
    Webflow slots:
      main-image         → image 1
      listing-images     → images 2-5  ("Top 4 Best Images")
      all-images         → images 1-5  ("Airbnb Top 5 Images")
      additional-images  → images 6+

    Codex review R2: extracted from build_field_data. Mutates
    `field_data` in place.
    """
    if not image_urls:
        return

    seen: set[str] = set()
    unique_urls: list[str] = []
    for url in image_urls:
        if url and url not in seen:
            seen.add(url)
            unique_urls.append(url)

    slug_types = {f["slug"]: f.get("type") for f in collection_fields}
    main = unique_urls[:1]
    top_four_after_main = unique_urls[1:5]
    airbnb_top_five = unique_urls[:5]
    rest = unique_urls[5:]

    if main and slug_types.get("main-image") == "Image":
        field_data["main-image"] = {"url": main[0], "alt": alt}

    if slug_types.get("listing-images") == "MultiImage":
        field_data["listing-images"] = [
            {"url": u, "alt": alt} for u in top_four_after_main
        ]

    if slug_types.get("all-images") == "MultiImage":
        field_data["all-images"] = [
            {"url": u, "alt": alt} for u in airbnb_top_five
        ]

    if slug_types.get("additional-images") == "MultiImage" and rest:
        field_data["additional-images"] = [
            {"url": u, "alt": alt} for u in rest
        ]


def build_field_data(
    row: dict,
    field_mapping: dict[str, str],
    image_urls: list[str],
    collection_fields: list[dict],
) -> dict:
    """Build the Webflow `fieldData` payload for a DB row.

    Composition:
      1. generic per-field type coercion via `_coerce_field_value`
      2. mandatory `name` + `slug` injection (Webflow requires both)
      3. price routing via `_route_price_to_field` (overrides the
         generic str() of price_numeric with the locale-aware display
         string and lands it on the correct slug per ad_type)
      4. image splitting via `_assign_image_fields`
    """
    field_types: dict[str, str] = {
        f.get("slug", ""): f.get("type", "PlainText")
        for f in collection_fields
    }
    available_slugs = set(field_types.keys())

    field_data: dict = {}
    for db_field, wf_slug in field_mapping.items():
        coerced = _coerce_field_value(
            db_field, wf_slug, row.get(db_field), field_types,
        )
        if coerced is not None:
            field_data[wf_slug] = coerced

    if "name" not in field_data:
        field_data["name"] = (
            row.get("title") or f"Nave industrial {row.get('listing_id', '')}"
        )
    field_data["slug"] = (
        row.get("webflow_slug") or f"nave-{row.get('listing_id', '')}"
    )

    _route_price_to_field(field_data, row, available_slugs)
    _assign_image_fields(
        field_data, image_urls, collection_fields, alt=field_data.get("name", ""),
    )

    return field_data


async def _build_source_url_index(
    client: WebflowClient,
    field_mapping: dict[str, str],
    cms_locale_id: str | None,
) -> dict[str, str]:
    """Return {source_url: item_id} from existing Webflow items.

    Empty when the collection has no `url`-style mapped slug — that's the
    common case until Benedict creates the `source-url` field. We never
    fail sync because of this; we just lose the Webflow-side dedup safety
    net for that run.
    """
    source_slug = field_mapping.get("url")
    if not source_slug:
        logger.info(
            "[Webflow] No source-url field mapped; skipping dedup index "
            "(blocks Tarea 6 until the Webflow schema exposes it)."
        )
        return {}

    try:
        items = await client.list_items(cms_locale_id=cms_locale_id)
    except Exception as e:
        logger.warning(
            "[Webflow] list_items failed; skipping dedup index this run: %s", e
        )
        return {}

    # Codex review B7: guard against the temporary `google-place-id`
    # stash sharing a slot with real Place IDs. If someone manually sets
    # a real Google Place ID in that field before Benedict creates
    # `source-url`, the index would otherwise treat the Place ID as a
    # MilAnuncios URL (and fail to match) — silently corrupting dedup
    # for that item. Filter to URL-shaped values only.
    index: dict[str, str] = {}
    for item in items:
        field_data = item.get("fieldData", {}) or {}
        raw = field_data.get(source_slug)
        if not raw:
            continue
        value = str(raw).strip()
        if not value.startswith(("http://", "https://")):
            continue
        index[value] = item.get("id", "")
    logger.info(
        "[Webflow] Dedup index built: %d items with source-url", len(index)
    )
    return index


async def sync_pending_listings() -> dict:
    """
    Sincroniza todos los anuncios pendientes (webflow_item_id IS NULL) con Webflow.
    Abre su propia conexión DB para no depender de la del endpoint.
    Retorna resumen {synced, failed, skipped}.
    """
    from integrations.webflow_client import COLLECTION_ID, WEBFLOW_TOKEN

    if not WEBFLOW_TOKEN or not COLLECTION_ID:
        logger.warning(
            "[Webflow] Sync skipped — WEBFLOW_TOKEN or WEBFLOW_COLLECTION_ID not configured"
        )
        return {"synced": 0, "failed": 0, "skipped": "unconfigured"}

    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")

    synced = 0
    failed = 0

    try:
        async with WebflowClient() as client:
            # Pre-flight: skip the rest of sync (and the expensive ~8 s
            # CMS pagination of _build_source_url_index) when there is
            # nothing to sync. Codex review Sprint 2 (P2).
            rows = get_unsynced_listings(conn)
            if not rows:
                logger.info("[Webflow] Sync skipped — 0 pending rows")
                return {"synced": 0, "failed": 0}

            # Descubrir schema de la colección
            schema = await client.get_collection_schema()
            field_mapping = resolve_field_mapping(schema)
            collection_fields = schema.get("fields", [])

            # Resolve Spanish locale for all items (MilAnuncios = Spanish)
            spanish_locale_id = await client.resolve_spanish_locale_id()
            locale_ids = [spanish_locale_id] if spanish_locale_id else None

            # Iteración 2026-05 (Tarea 6): build a {source_url: item_id} dedup
            # index from the existing CMS items so we can short-circuit
            # creation when the listing was already synced (or exists as a
            # leftover draft from a previous run). The index is a no-op when
            # the schema does not expose a `source-url`-style slug yet.
            source_url_index = await _build_source_url_index(
                client, field_mapping, spanish_locale_id,
            )

            logger.info("[Webflow] Iniciando sync: %d anuncios pendientes", len(rows))

            for row in rows:
                listing_id = row.get("listing_id", "")
                row_url = (row.get("url") or "").strip()

                # Webflow-side dedup: if an existing item already references
                # this listing's URL, adopt its item_id and skip creation.
                if source_url_index and row_url and row_url in source_url_index:
                    existing_id = source_url_index[row_url]
                    update_webflow_id(conn, listing_id, existing_id)
                    synced += 1
                    logger.info(
                        "[SKIP-WEBFLOW] %s ya existe como %s (source-url match)",
                        listing_id, existing_id,
                    )
                    continue

                # Image upload fallback chain: Webflow Assets → Cloudinary
                # → raw MilAnuncios URLs. See webflow_image_uploader.py.
                image_urls, cloudinary_public_ids = await upload_listing_images(client, row)

                # Construir y enviar item
                try:
                    field_data = build_field_data(row, field_mapping, image_urls, collection_fields)
                    item_id = await client.create_item_draft(field_data, cms_locale_ids=locale_ids)
                    update_webflow_id(conn, listing_id, item_id)
                    synced += 1
                    logger.info(
                        "[Webflow] ✓ %s → item %s (%d imágenes)",
                        listing_id, item_id, len(image_urls),
                    )
                except httpx.HTTPStatusError as e:
                    failed += 1
                    status_code = e.response.status_code
                    response_text = e.response.text[:300]
                    # 409 means Webflow already has something at this slug.
                    # With the title-based unique slug system in place this
                    # points to an external/manual edit worth investigating —
                    # leave the row unsynced so it is retried (or picked up
                    # manually) rather than silently marking it DUPLICATE.
                    logger.error(
                        "[Webflow] ✗ %s: HTTP %s — %s",
                        listing_id, status_code, response_text,
                    )
                except Exception as e:
                    failed += 1
                    logger.error("[Webflow] ✗ %s: %s", listing_id, e)
                finally:
                    # Clean up Cloudinary staging assets regardless of the
                    # create_item_draft outcome: on success, Webflow has
                    # already re-hosted the file on its own CDN and no
                    # longer needs the Cloudinary copy; on failure, the
                    # next retry will re-upload with `overwrite=True`, so
                    # there is no point keeping the stale copy around.
                    if cloudinary_public_ids:
                        deleted = await cloudinary_delete_images(cloudinary_public_ids)
                        logger.info(
                            "[Cloudinary] %s: borrados %d/%d assets temporales",
                            listing_id, deleted, len(cloudinary_public_ids),
                        )

                # Respetar rate limit de Webflow (~2 req/s para escritura)
                await asyncio.sleep(0.6)

    finally:
        conn.close()

    logger.info("[Webflow] Sync completado: %d sincronizados, %d fallidos", synced, failed)
    return {"synced": synced, "failed": failed}
