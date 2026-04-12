"""
Cliente asíncrono para la API v2 de Webflow CMS.

Flujo de upload de imagen (requerido por v2):
  1. POST /sites/{siteId}/assets  → obtiene uploadUrl (S3 pre-signed) + hostedUrl
  2. POST {uploadUrl} multipart   → sube el archivo a S3
  Después usar hostedUrl en fieldData de los items.

Crear item como draft:
  POST /collections/{collectionId}/items  body: {isDraft:true, fieldData:{...}}
"""
import hashlib
import logging
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

WEBFLOW_BASE = "https://api.webflow.com/v2"
WEBFLOW_TOKEN = os.getenv("WEBFLOW_TOKEN", "")
COLLECTION_ID = os.getenv("WEBFLOW_COLLECTION_ID", "673373bb232280f5720b72ca")
SITE_ID_ENV = os.getenv("WEBFLOW_SITE_ID", "")


class WebflowClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=WEBFLOW_BASE,
            headers={
                "Authorization": f"Bearer {WEBFLOW_TOKEN}",
                "accept": "application/json",
                "content-type": "application/json",
            },
            timeout=30.0,
        )
        self._site_id: str | None = None
        self._collection_schema: dict | None = None
        self._site_locales: list[dict] | None = None

    async def get_collection_schema(self) -> dict:
        """GET /collections/{id} — devuelve el schema con todos los campos."""
        if self._collection_schema:
            return self._collection_schema
        r = await self._client.get(f"/collections/{COLLECTION_ID}")
        r.raise_for_status()
        self._collection_schema = r.json()
        fields = [f.get("slug", "") for f in self._collection_schema.get("fields", [])]
        logger.info("[Webflow] Campos disponibles en la colección: %s", fields)
        return self._collection_schema

    async def get_site_id(self) -> str:
        """
        Webflow v2 collection schema no longer carries `siteId`, so we
        resolve it from the `/sites` endpoint (optionally pinned via the
        `WEBFLOW_SITE_ID` env var to avoid a round-trip and to disambiguate
        multi-site workspaces).
        """
        if self._site_id:
            return self._site_id
        if SITE_ID_ENV:
            self._site_id = SITE_ID_ENV
            return self._site_id
        r = await self._client.get("/sites")
        r.raise_for_status()
        sites = r.json().get("sites", [])
        if not sites:
            raise ValueError("No se pudo obtener siteId — /sites devolvió vacío")
        self._site_id = sites[0].get("id", "")
        if not self._site_id:
            raise ValueError("No se pudo obtener siteId — campo 'id' ausente")
        return self._site_id

    async def get_site_locales(self) -> list[dict]:
        """Fetch available locales from GET /sites/{siteId}.
        Returns a flat list of {cmsLocaleId, tag, primary} dicts.
        Returns [] if localization is not enabled on the site."""
        if self._site_locales is not None:
            return self._site_locales
        site_id = await self.get_site_id()
        try:
            r = await self._client.get(f"/sites/{site_id}")
            r.raise_for_status()
        except Exception as e:
            logger.warning("[Webflow] Could not fetch site locales: %s", e)
            self._site_locales = []
            return self._site_locales
        locales_data = r.json().get("locales", {})
        if not locales_data:
            self._site_locales = []
            return self._site_locales
        result: list[dict] = []
        primary = locales_data.get("primary")
        if primary and primary.get("cmsLocaleId"):
            result.append({
                "cmsLocaleId": primary["cmsLocaleId"],
                "tag": primary.get("tag", ""),
                "primary": True,
            })
        for sec in locales_data.get("secondary", []):
            if sec.get("cmsLocaleId"):
                result.append({
                    "cmsLocaleId": sec["cmsLocaleId"],
                    "tag": sec.get("tag", ""),
                    "primary": False,
                })
        self._site_locales = result
        logger.info(
            "[Webflow] Site locales: %s",
            [(l["tag"], l["cmsLocaleId"][:8]) for l in result],
        )
        return self._site_locales

    async def resolve_spanish_locale_id(self) -> str | None:
        """Find the cmsLocaleId for the Spanish locale.
        Returns None if localization is disabled or Spanish is not configured."""
        locales = await self.get_site_locales()
        if not locales:
            logger.info("[Webflow] Localization not enabled on this site")
            return None
        for loc in locales:
            tag = loc.get("tag", "").lower()
            if tag == "es" or tag.startswith("es-"):
                logger.info(
                    "[Webflow] Spanish locale found: tag=%s cmsLocaleId=%s",
                    loc["tag"], loc["cmsLocaleId"],
                )
                return loc["cmsLocaleId"]
        logger.warning(
            "[Webflow] Site has localization but no Spanish locale found "
            "(available: %s)",
            [l["tag"] for l in locales],
        )
        return None

    async def upload_asset(self, file_path: str, filename: str) -> str | None:
        """
        Sube un archivo a Webflow Assets v2 usando el flujo de S3 pre-signed.
        Retorna la URL del CDN de Webflow (hostedUrl), o None si falla.
        """
        site_id = await self.get_site_id()
        file_bytes = Path(file_path).read_bytes()
        file_hash = hashlib.md5(file_bytes).hexdigest()

        # Paso 1: solicitar URL de upload
        r = await self._client.post(
            f"/sites/{site_id}/assets",
            json={"fileName": filename, "fileHash": file_hash},
        )
        if r.status_code == 404:
            logger.warning("[Webflow] Assets API no disponible (plan sin soporte de assets)")
            return None
        r.raise_for_status()
        data = r.json()

        upload_url: str = data.get("uploadUrl", "")
        upload_details: dict = data.get("uploadDetails", {})
        hosted_url: str = data.get("hostedUrl", "")

        if not upload_url:
            logger.warning("[Webflow] No se recibió uploadUrl para %s", filename)
            return hosted_url or None

        # Paso 2: subir archivo a S3 (sin headers de auth de Webflow)
        # Los uploadDetails son los campos del form multipart de S3.
        # S3 pre-signed URLs validate the content-type, so infer from the
        # filename extension when uploadDetails does not pin one.
        ext = Path(filename).suffix.lower().lstrip(".")
        default_ct = {
            "webp": "image/webp",
            "png":  "image/png",
            "gif":  "image/gif",
            "jpg":  "image/jpeg",
            "jpeg": "image/jpeg",
        }.get(ext, "image/jpeg")
        content_type = upload_details.get("Content-Type", default_ct)
        form_fields = {k: (None, v) for k, v in upload_details.items() if k != "Content-Type"}
        form_fields["file"] = (filename, file_bytes, content_type)

        async with httpx.AsyncClient(timeout=60.0) as s3_client:
            s3_r = await s3_client.post(upload_url, files=form_fields)
            if s3_r.status_code not in (200, 204):
                logger.warning(
                    "[Webflow] S3 upload falló %s: %s", filename, s3_r.status_code
                )
                return None

        logger.debug("[Webflow] Imagen subida: %s → %s", filename, hosted_url)
        return hosted_url

    async def create_item_draft(
        self, field_data: dict, cms_locale_ids: list[str] | None = None,
    ) -> str:
        """
        Crea un item CMS como draft (no publicado).
        If cms_locale_ids is provided, the item is created for those locales.
        Retorna el ID del item creado.
        """
        payload = {
            "isArchived": False,
            "isDraft": True,
            "fieldData": field_data,
        }
        if cms_locale_ids:
            payload["cmsLocaleIds"] = cms_locale_ids
        r = await self._client.post(
            f"/collections/{COLLECTION_ID}/items",
            json=payload,
        )
        if r.status_code == 400:
            logger.error(
                "[Webflow] Error 400 creando item. Payload: %s\nRespuesta: %s",
                field_data,
                r.text[:500],
            )
        r.raise_for_status()
        item = r.json()
        return item.get("id", item.get("_id", ""))

    async def update_items(
        self, updates: list[dict], cms_locale_id: str | None = None,
    ) -> dict:
        """
        Batch-update existing CMS items.

        `updates` is a list of `{"id": item_id, "fieldData": {...}}`
        dicts — matching the shape Webflow v2 expects under
        PATCH /collections/{id}/items. Requests are chunked to 100
        items (the documented v2 limit).

        If cms_locale_id is provided, it is injected into each item
        object so the update targets that specific locale variant.

        Returns {"updated": int, "errors": list[str]}.
        """
        if not updates:
            return {"updated": 0, "errors": []}

        if cms_locale_id:
            updates = [
                {**item, "cmsLocaleId": cms_locale_id} for item in updates
            ]

        updated = 0
        errors: list[str] = []
        for i in range(0, len(updates), 100):
            chunk = updates[i : i + 100]
            try:
                r = await self._client.patch(
                    f"/collections/{COLLECTION_ID}/items",
                    json={"items": chunk},
                )
                if r.status_code >= 400:
                    logger.error(
                        "[Webflow] update_items HTTP %s on chunk %d-%d: %s",
                        r.status_code, i, i + len(chunk), r.text[:300],
                    )
                    errors.append(f"chunk {i}: HTTP {r.status_code} {r.text[:200]}")
                    continue
                updated += len(chunk)
            except Exception as e:
                logger.error(
                    "[Webflow] update_items exception on chunk %d-%d: %s",
                    i, i + len(chunk), e,
                )
                errors.append(f"chunk {i}: {e}")

        return {"updated": updated, "errors": errors}

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "WebflowClient":
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()
