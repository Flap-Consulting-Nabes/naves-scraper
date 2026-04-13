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
import sqlite3
from pathlib import Path

import httpx
from dotenv import load_dotenv

from db import get_unsynced_listings, init_db, update_webflow_id
from integrations.cloudinary_client import delete_images as cloudinary_delete_images
from integrations.webflow_client import WebflowClient
from integrations.webflow_image_uploader import upload_listing_images

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
    "seller_type":      ["seller-type", "tipo-vendedor", "tipo-anunciante"],
    "seller_name":      ["seller", "vendedor", "agencia", "anunciante", "empresa"],
    "phone":            ["phone", "telefono", "teléfono", "contacto"],
    "url":              ["source-url", "url", "link", "enlace", "url-origen"],
    "published_at":     ["published-date", "fecha-publicacion", "fecha-anuncio", "publish-date"],
}


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
        logger.info(
            "[Webflow] Campos DB sin mapeo en la colección (se omitirán): %s", unmatched
        )
    logger.info("[Webflow] Campos mapeados (%d): %s", len(resolved), list(resolved.values()))
    return resolved


def build_field_data(
    row: dict,
    field_mapping: dict[str, str],
    image_urls: list[str],
    collection_fields: list[dict],
) -> dict:
    """
    Construye el payload fieldData para Webflow a partir de una fila de la DB.
    """
    # Índice de tipo por slug para formatear valores correctamente
    field_types: dict[str, str] = {
        f.get("slug", ""): f.get("type", "PlainText")
        for f in collection_fields
    }

    field_data: dict = {}

    for db_field, wf_slug in field_mapping.items():
        value = row.get(db_field)
        if value is None:
            continue

        ftype = field_types.get(wf_slug, "PlainText")

        # Convertir según tipo de campo Webflow
        if ftype in ("Number",):
            try:
                field_data[wf_slug] = float(value)
            except (TypeError, ValueError):
                pass
        elif ftype in ("Date", "DateTime"):
            # Webflow espera ISO 8601
            if isinstance(value, str) and value:
                if "T" not in value:
                    value = value + "T00:00:00.000Z"
                field_data[wf_slug] = value
        else:
            field_data[wf_slug] = str(value) if value is not None else None

    # "name" es siempre requerido en Webflow
    if "name" not in field_data:
        field_data["name"] = row.get("title") or f"Nave industrial {row.get('listing_id', '')}"

    # Slug: use the title-based slug computed at scrape time. Fallback to
    # `nave-{listing_id}` for legacy rows that have not been back-filled yet.
    field_data["slug"] = row.get("webflow_slug") or f"nave-{row.get('listing_id', '')}"

    # Imágenes: campo Multi-image de Webflow
    if image_urls:
        # Detectar qué campos de imagen existen en la colección
        available_slugs = {f["slug"]: f.get("type") for f in collection_fields}
        
        # 1. Imagen principal (tipo Image, un solo objeto)
        if "main-image" in available_slugs and available_slugs["main-image"] == "Image":
            field_data["main-image"] = {"url": image_urls[0], "alt": field_data.get("name", "")}
            
        # 2. Galería de imágenes (tipo MultiImage, array de objetos)
        multi_image_payload = [
            {"url": url, "alt": field_data.get("name", "")}
            for url in image_urls
        ]
        
        for slug in ["listing-images", "all-images"]:
            if slug in available_slugs and available_slugs[slug] == "MultiImage":
                field_data[slug] = multi_image_payload

    return field_data


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

    synced = 0
    failed = 0

    try:
        async with WebflowClient() as client:
            # Descubrir schema de la colección
            schema = await client.get_collection_schema()
            field_mapping = resolve_field_mapping(schema)
            collection_fields = schema.get("fields", [])

            # Resolve Spanish locale for all items (MilAnuncios = Spanish)
            spanish_locale_id = await client.resolve_spanish_locale_id()
            locale_ids = [spanish_locale_id] if spanish_locale_id else None

            rows = get_unsynced_listings(conn)
            logger.info("[Webflow] Iniciando sync: %d anuncios pendientes", len(rows))

            for row in rows:
                listing_id = row.get("listing_id", "")

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
