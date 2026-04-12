"""
WebP image compressor used by `utils.image_downloader` (new listings) and
`scripts.migrate_images` (one-shot back-fill).

Defaults chosen for the "balanced" profile agreed with Alejandro:
  quality=80  → ~40–70 KB per typical listing photo
  max_dim=1200 → long edge capped at 1200 px, preserves aspect ratio
  method=6    → Pillow's slowest/best WebP encoder setting

Keeping this in its own module lets the download path and the migration
script share the exact same encoder settings — and keeps
`image_downloader.py` under the 300-line limit.
"""
from io import BytesIO
from pathlib import Path

from PIL import Image

DEFAULT_QUALITY = 80
DEFAULT_MAX_DIM = 1200


def compress_to_webp(
    src: bytes | bytearray | Path | str,
    dst: Path | str,
    quality: int = DEFAULT_QUALITY,
    max_dim: int = DEFAULT_MAX_DIM,
) -> int:
    """
    Load an image from bytes or a path, resize to `max_dim` with LANCZOS
    if needed, and save as WebP at the given quality.

    Returns the final file size in bytes.
    """
    dst_path = Path(dst)

    if isinstance(src, (bytes, bytearray)):
        img = Image.open(BytesIO(src))
    else:
        img = Image.open(Path(src))

    # WebP rejects palette / alpha modes from some source images — normalise
    # to RGB. Listings never need transparency.
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # thumbnail() preserves aspect ratio and only shrinks — never upscales.
    img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst_path, "WEBP", quality=quality, method=6)
    return dst_path.stat().st_size
