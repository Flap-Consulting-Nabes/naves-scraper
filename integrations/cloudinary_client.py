"""
Cloudinary uploader — intermediate public host so Webflow picks up
slug-based filenames.

Why this exists
---------------
Webflow's CDN re-hosts remote images using the **last path segment** of
the source URL as the base filename. When the scraper falls back to the
MilAnuncios remote URL (because `WEBFLOW_TOKEN` lacks `assets:read` /
`assets:write`), that last segment is a UUID like
`bd808315-11ad-4151-957b-c5a6fbfdae1c`, so the Webflow CDN ends up with
names like `{asset-id}_bd808315-....webp` — useless for SEO.

Cloudinary lets us stage each image under a deterministic `public_id`
equal to the slug-based filename we already generated (e.g.
`poligono-las-salinas-image-1`). When Webflow then downloads from
`https://res.cloudinary.com/.../poligono-las-salinas-image-1.webp`, the
last path segment is the slug, so the CDN filename becomes
`{asset-id}_poligono-las-salinas-image-1.webp` — SEO-friendly.

Configuration
-------------
Reads three env vars (all required for the upload to succeed):
  - `CLOUDINARY_CLOUD_NAME`
  - `CLOUDINARY_API_KEY`
  - `CLOUDINARY_API_SECRET`

If any are missing, `upload_image()` returns `None` without raising, so
the caller can fall through to the next fallback path.
"""
import asyncio
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_CONFIGURED: bool | None = None


def _ensure_configured() -> bool:
    """Lazy one-shot config — avoids import-time failures when the env
    vars are missing. Returns True iff Cloudinary is usable."""
    global _CONFIGURED
    if _CONFIGURED is not None:
        return _CONFIGURED

    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
    api_key = os.getenv("CLOUDINARY_API_KEY", "").strip()
    api_secret = os.getenv("CLOUDINARY_API_SECRET", "").strip()

    if not (cloud_name and api_key and api_secret):
        logger.info(
            "[Cloudinary] credenciales no configuradas "
            "(CLOUDINARY_CLOUD_NAME/API_KEY/API_SECRET); "
            "se omite el paso intermedio"
        )
        _CONFIGURED = False
        return False

    try:
        import cloudinary  # type: ignore
        cloudinary.config(
            cloud_name=cloud_name,
            api_key=api_key,
            api_secret=api_secret,
            secure=True,
        )
        _CONFIGURED = True
        logger.info("[Cloudinary] configurado con cloud_name=%s", cloud_name)
        return True
    except ImportError:
        logger.warning(
            "[Cloudinary] paquete `cloudinary` no instalado; "
            "ejecuta `pip install cloudinary` para habilitar el host intermedio"
        )
        _CONFIGURED = False
        return False


def _upload_sync(local_path: str, public_id: str) -> str | None:
    """Blocking Cloudinary upload. Called from a worker thread via
    `asyncio.to_thread` so it does not stall the event loop."""
    try:
        import cloudinary.uploader  # type: ignore
        result = cloudinary.uploader.upload(
            local_path,
            public_id=public_id,
            folder="milanuncios",
            overwrite=True,
            resource_type="image",
            use_filename=False,
            unique_filename=False,
        )
    except Exception as e:
        logger.warning(
            "[Cloudinary] upload falló para %s (public_id=%s): %s",
            local_path, public_id, e,
        )
        return None

    secure_url = result.get("secure_url") or result.get("url")
    if not secure_url:
        logger.warning(
            "[Cloudinary] respuesta sin secure_url para %s: %s",
            local_path, result,
        )
        return None
    return secure_url


async def upload_image(local_path: str | Path, public_id: str) -> str | None:
    """
    Upload `local_path` to Cloudinary with `public_id` as the deterministic
    asset name. Returns the Cloudinary `secure_url` on success, or `None`
    if Cloudinary is not configured or the upload fails.

    `public_id` should be the filename stem without extension
    (e.g. `poligono-las-salinas-image-1`). Cloudinary appends the correct
    extension automatically based on the uploaded file's content.
    """
    if not _ensure_configured():
        return None

    path_str = str(local_path)
    if not Path(path_str).exists():
        logger.warning("[Cloudinary] archivo no existe: %s", path_str)
        return None

    return await asyncio.to_thread(_upload_sync, path_str, public_id)


def _delete_sync(public_id: str) -> bool:
    """Blocking Cloudinary delete. Called from a worker thread."""
    try:
        import cloudinary.uploader  # type: ignore
        result = cloudinary.uploader.destroy(
            f"milanuncios/{public_id}",
            resource_type="image",
            invalidate=True,
        )
    except Exception as e:
        logger.warning(
            "[Cloudinary] delete falló public_id=%s: %s", public_id, e,
        )
        return False

    # Cloudinary returns {"result": "ok"} on success, {"result": "not found"}
    # if the asset was already gone.
    outcome = result.get("result", "")
    if outcome not in ("ok", "not found"):
        logger.warning(
            "[Cloudinary] delete respuesta inesperada public_id=%s: %s",
            public_id, result,
        )
        return False
    return True


async def delete_image(public_id: str) -> bool:
    """
    Delete a single Cloudinary asset by its `public_id` (stem only — the
    `milanuncios/` folder prefix is added internally to match the upload
    layout). Returns True on success or if the asset was already gone.
    Never raises — failures are logged and returned as False.
    """
    if not _ensure_configured():
        return False
    return await asyncio.to_thread(_delete_sync, public_id)


async def delete_images(public_ids: list[str]) -> int:
    """
    Delete multiple Cloudinary assets in parallel. Returns the number of
    successful deletions. Used to clean up staging uploads after Webflow
    has re-hosted them on its own CDN, keeping the free-tier storage low.
    """
    if not public_ids:
        return 0
    if not _ensure_configured():
        return 0
    results = await asyncio.gather(
        *(delete_image(pid) for pid in public_ids),
        return_exceptions=True,
    )
    return sum(1 for r in results if r is True)
