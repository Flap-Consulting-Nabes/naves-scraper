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
        if self._site_id:
            return self._site_id
        schema = await self.get_collection_schema()
        self._site_id = schema.get("siteId") or schema.get("site_id", "")
        if not self._site_id:
            raise ValueError("No se pudo obtener siteId de la colección Webflow")
        return self._site_id

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
        # Los uploadDetails son los campos del form multipart de S3
        content_type = upload_details.get("Content-Type", "image/jpeg")
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

    async def create_item_draft(self, field_data: dict) -> str:
        """
        Crea un item CMS como draft (no publicado).
        Retorna el ID del item creado.
        """
        payload = {
            "isArchived": False,
            "isDraft": True,
            "fieldData": field_data,
        }
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

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "WebflowClient":
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()
