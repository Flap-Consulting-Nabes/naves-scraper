"""
One-shot introspection of the Webflow CMS collection schema.

Dumps every field (slug, type, displayName, required, validations) and
highlights the fields relevant to the May 2026 client-feedback iteration:
source-url, additional-images, latitude, longitude, Map field, description
type (RichText/PlainText/Textarea), phone2.

Usage:
    python scripts/inspect_webflow_schema.py
    python scripts/inspect_webflow_schema.py --json-out docs/webflow-schema.json

Reads WEBFLOW_TOKEN and WEBFLOW_COLLECTION_ID from the environment.
"""
import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from integrations.webflow_client import WebflowClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("inspect_webflow_schema")

DEFAULT_JSON_OUT = Path("docs") / "webflow-schema.json"

INTEREST_GROUPS: dict[str, list[str]] = {
    "Source URL (Task 7)": ["source-url", "source_url", "url", "link", "enlace", "url-origen"],
    "Additional images (Task 3)": ["additional-images", "additional_images", "extra-images", "more-images"],
    "Latitude (Task 9)": ["latitude", "lat"],
    "Longitude (Task 9)": ["longitude", "lng", "lon"],
    "Map field (Task 9)": ["location-map", "map", "ubicacion-map", "geo"],
    "Description (Task 4)": ["description", "descripcion", "descripción", "contenido"],
    "Main image (Task 3)": ["main-image", "main_image", "imagen-principal"],
    "Listing images (Task 3)": ["listing-images", "all-images", "gallery", "galeria"],
    "Phone 1 (Task 8)": ["phone", "telefono", "teléfono", "contacto"],
    "Phone 2 (Task 8)": ["phone-2", "phone2", "telefono-2", "segundo-telefono"],
    "Title (Task 2)": ["name", "title", "nombre", "titulo"],
    "Slug (Task 2)": ["slug"],
    "Ad type (Task 1)": ["ad-type", "ad_type", "tipo-operacion", "tipo-anuncio", "operacion"],
    "Price (Task 5)": ["price", "precio", "new-sale-price", "precio-venta", "precio-alquiler"],
    "Price per m2 (Task 5)": ["price-per-m2", "precio-m2", "precio-metro", "new-price-sm2-month"],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json-out",
        type=Path,
        default=DEFAULT_JSON_OUT,
        help=f"Path to write the raw schema JSON (default: {DEFAULT_JSON_OUT})",
    )
    return parser.parse_args()


def summarize_field(f: dict) -> dict:
    return {
        "slug": f.get("slug", ""),
        "displayName": f.get("displayName", ""),
        "type": f.get("type", ""),
        "isRequired": f.get("isRequired", False),
        "isEditable": f.get("isEditable", True),
        "validations": f.get("validations", {}),
    }


def find_match(fields: list[dict], candidates: list[str]) -> dict | None:
    for f in fields:
        if f.get("slug", "") in candidates:
            return f
    return None


async def main() -> int:
    args = parse_args()

    async with WebflowClient() as client:
        try:
            schema = await client.get_collection_schema()
        except Exception as e:
            logger.error("Failed to fetch schema: %s", e)
            return 1

    fields = schema.get("fields", [])
    logger.info(
        "Collection: %s (id=%s) — %d fields",
        schema.get("displayName", "?"),
        schema.get("id", "?"),
        len(fields),
    )

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    with args.json_out.open("w", encoding="utf-8") as fh:
        json.dump(schema, fh, indent=2, ensure_ascii=False)
    logger.info("Raw schema written to %s", args.json_out)

    print("\n" + "=" * 70)
    print("ALL FIELDS")
    print("=" * 70)
    for f in fields:
        s = summarize_field(f)
        required = " *required" if s["isRequired"] else ""
        print(f"  {s['slug']:<35} {s['type']:<15} {s['displayName']}{required}")

    print("\n" + "=" * 70)
    print("RELEVANT FIELDS FOR THE 9 ITERATION TASKS")
    print("=" * 70)
    for label, candidates in INTEREST_GROUPS.items():
        match = find_match(fields, candidates)
        if match:
            s = summarize_field(match)
            print(f"  [FOUND ] {label}")
            print(f"           slug={s['slug']}  type={s['type']}  required={s['isRequired']}")
        else:
            print(f"  [MISSING] {label}  — none of {candidates} found")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
