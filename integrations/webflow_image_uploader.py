"""
Three-step image fallback chain used by `integrations/webflow_sync.py`.

For each local WebP referenced by a listing row, try in order:
  1. **Webflow Assets API** — native upload. Fails with HTTP 403 until the
     user regenerates `WEBFLOW_TOKEN` with `assets:read` / `assets:write`.
  2. **Cloudinary staging host** — uploads the file with a deterministic
     `public_id` equal to the slug-based filename stem. Webflow then
     downloads from `res.cloudinary.com/.../poligono-las-salinas-image-1`
     and re-hosts under the same basename, giving us SEO-friendly CDN URLs.
  3. **Raw MilAnuncios remote URL** — last-ditch fallback so items never
     land imageless. Loud warning: Webflow will re-host these with UUID
     basenames until either Webflow Assets or Cloudinary starts working.

Returns `(image_urls, cloudinary_public_ids)` so the caller can delete
the staging Cloudinary assets once the Webflow item has been created.

Kept in its own module so `webflow_sync.py` stays under the 300-line cap
mandated by CLAUDE.md rule 2.
"""
import json
import logging
from pathlib import Path

from integrations.cloudinary_client import upload_image as cloudinary_upload
from integrations.webflow_client import WebflowClient

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent

MAX_IMAGES_PER_LISTING = 10


async def upload_listing_images(
    client: WebflowClient,
    row: dict,
) -> tuple[list[str], list[str]]:
    """
    Produce a list of public image URLs for a listing row, trying the
    Webflow Assets API first, then Cloudinary, finally falling back to the
    raw MilAnuncios remote URLs on the `photos` column.

    Returns:
        image_urls: URLs ready to feed into a Webflow `fieldData` image
            field. Empty only when neither local nor remote images exist.
        cloudinary_public_ids: the `public_id`s we successfully uploaded to
            Cloudinary during this call. The caller is responsible for
            deleting these staging assets after the Webflow item has been
            created (see `cloudinary_client.delete_images`).
    """
    listing_id = row.get("listing_id", "")
    image_urls: list[str] = []
    cloudinary_public_ids: list[str] = []

    images_local_raw = row.get("images_local")
    photos_raw = row.get("photos")

    # ── Step 1 & 2: iterate local WebPs, try Webflow then Cloudinary ─────
    if images_local_raw and images_local_raw != "null":
        try:
            local_paths: list[str] = json.loads(images_local_raw)
        except (json.JSONDecodeError, TypeError):
            local_paths = []

        for local_path in local_paths[:MAX_IMAGES_PER_LISTING]:
            full_path = (
                local_path
                if Path(local_path).is_absolute()
                else str(PROJECT_ROOT / local_path)
            )
            if not Path(full_path).exists():
                continue

            filename = Path(full_path).name
            # `public_id` = filename stem (e.g. poligono-las-salinas-image-1)
            # so both Cloudinary and the eventual Webflow CDN re-host keep
            # the slug-based name for SEO.
            public_id = Path(full_path).stem
            hosted_url: str | None = None

            # 1) Webflow Assets API — native upload.
            try:
                hosted_url = await client.upload_asset(full_path, filename)
            except Exception as e:
                logger.debug(
                    "[Webflow] Assets upload no disponible %s: %s",
                    local_path, e,
                )

            # 2) Cloudinary staging host.
            if not hosted_url:
                try:
                    hosted_url = await cloudinary_upload(full_path, public_id)
                    if hosted_url:
                        cloudinary_public_ids.append(public_id)
                except Exception as e:
                    logger.warning(
                        "[Webflow] Cloudinary upload falló %s: %s",
                        local_path, e,
                    )

            if hosted_url:
                image_urls.append(hosted_url)

    # ── Step 3: raw remote URLs as a last-ditch fallback ─────────────────
    if not image_urls and photos_raw and photos_raw != "null":
        try:
            remote_urls = json.loads(photos_raw)
            image_urls.extend(remote_urls[:MAX_IMAGES_PER_LISTING])
            logger.warning(
                "[Webflow] %s: ni Webflow Assets ni Cloudinary produjeron "
                "URLs hospedadas; usando URLs remotas de MilAnuncios "
                "(%d imágenes). Configura CLOUDINARY_CLOUD_NAME/API_KEY/"
                "API_SECRET o regenera WEBFLOW_TOKEN con assets:read/"
                "assets:write — en caso contrario Webflow re-hospedará "
                "con nombres basados en hash en lugar de los slugs SEO.",
                listing_id, len(image_urls),
            )
        except (json.JSONDecodeError, TypeError):
            pass

    return image_urls, cloudinary_public_ids
