"""Individual field parsers for MilAnuncios listing pages.

Codex review R1: extracted from `integrations/parser.py`. Each function
takes BeautifulSoup and/or the parsed `__INITIAL_PROPS__` JSON dict and
returns a single typed value. They are stateless and pure — no network,
no I/O. Re-exported from `integrations.parser` for backward
compatibility.
"""
from __future__ import annotations

import json
import logging
import re

from bs4 import BeautifulSoup

from integrations.parser_core import _get_attribute_value

logger = logging.getLogger(__name__)


# ── ID ──────────────────────────────────────────────────────────────────────

def parse_listing_id(url: str) -> str | None:
    """Extract the numeric listing id from the URL.

    Example: `/naves-industriales/nave-industrial-en-venta-123456789.htm`
    → `'123456789'`.
    """
    match = re.search(r"-(\d{6,12})\.htm", url)
    if match:
        return match.group(1)
    # Fallback: trailing numeric segment.
    match = re.search(r"/(\d{6,12})(?:/|\.htm|$)", url)
    if match:
        return match.group(1)
    logger.warning(f"No se pudo extraer listing_id de: {url}")
    return None


# ── Title ───────────────────────────────────────────────────────────────────

def parse_title(soup: BeautifulSoup) -> str | None:
    tag = soup.find("h1")
    if tag:
        # Coger solo el texto directo del h1 (ignorar hijos como el botón de favoritos)
        direct_text = "".join(t for t in tag.strings if t.parent == tag).strip()
        if direct_text:
            return direct_text
        first = next(tag.strings, None)
        return first.strip() if first else None
    return None


# ── Price ───────────────────────────────────────────────────────────────────

def parse_price(soup: BeautifulSoup, ad_json: dict | None = None) -> str | None:
    if ad_json:
        cash = ad_json.get("price", {}).get("cashPrice", {})
        value = cash.get("value")
        if value is not None:
            return f"{int(value):,}".replace(",", ".") + " €"

    for selector in [
        "[class*='price']",
        "[class*='Price']",
        "[data-testid='ad-price']",
        "span[class*='precio']",
    ]:
        tag = soup.select_one(selector)
        if tag:
            text = tag.get_text(strip=True)
            if text:
                return text

    for tag in soup.find_all(string=re.compile(r"\d[\d\.\s]*€")):
        text = tag.strip()
        if text:
            return text

    return None


def parse_price_numeric(ad_json: dict | None) -> float | None:
    """Devuelve el precio como número limpio (sin símbolo €)."""
    if not ad_json:
        return None
    cash = ad_json.get("price", {}).get("cashPrice", {})
    value = cash.get("value")
    if value is not None:
        try:
            return float(value)
        except (ValueError, TypeError):
            pass
    return None


def parse_price_per_m2(ad_json: dict | None, soup: BeautifulSoup | None = None) -> float | None:
    """Extrae el precio por m² desde el JSON de atributos."""
    if ad_json:
        raw = _get_attribute_value(ad_json.get("attributes", []), "squareMeterPrice")
        if raw:
            try:
                return float(raw)
            except (ValueError, TypeError):
                pass
    if soup:
        text = soup.get_text()
        m = re.search(r"([\d\.,]+)\s*€\s*/\s*m[²2]", text)
        if m:
            try:
                return float(m.group(1).replace(".", "").replace(",", "."))
            except ValueError:
                pass
    return None


# ── Description ─────────────────────────────────────────────────────────────

def parse_description(soup: BeautifulSoup, ad_json: dict | None = None) -> str | None:
    if ad_json:
        desc = ad_json.get("description")
        if desc and len(desc) > 10:
            return desc

    for selector in [
        "[class*='description']",
        "[class*='Description']",
        "[data-testid='ad-description']",
        "div[class*='descripcion']",
        "p[class*='descripcion']",
    ]:
        tag = soup.select_one(selector)
        if tag:
            text = tag.get_text(separator="\n", strip=True)
            if len(text) > 20:
                return text
    return None


# ── Surface (m²) ────────────────────────────────────────────────────────────

def parse_surface(soup: BeautifulSoup, ad_json: dict | None = None) -> float | None:
    """Busca el valor numérico de la superficie en m²."""
    if ad_json:
        raw = _get_attribute_value(ad_json.get("attributes", []), "squareMeters")
        if raw:
            try:
                value = float(raw.replace(".", "").replace(",", "."))
                if value >= 10:
                    return value
            except (ValueError, TypeError):
                pass

    text = soup.get_text()
    patterns = [
        r"(\d[\d\.,]*)\s*m[²2]",
        r"superficie[:\s]+(\d[\d\.,]*)",
        r"(\d[\d\.,]*)\s*metros",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            raw = match.group(1).replace(".", "").replace(",", ".")
            try:
                value = float(raw)
                if value >= 10:
                    return value
            except ValueError:
                continue
    return None


# ── Location + coordinates + address + zipcode ─────────────────────────────

def parse_location(
    soup: BeautifulSoup, url: str = "", ad_json: dict | None = None,
) -> tuple[str | None, str | None]:
    """Devuelve (location_text, province)."""
    location = None
    province = None

    if ad_json:
        loc = ad_json.get("location", {})
        city_obj = loc.get("city", {})
        prov_obj = loc.get("province", {})
        city_name = city_obj.get("name")
        prov_name = prov_obj.get("name")
        if city_name:
            location = city_name
            if prov_name:
                location = f"{city_name} ({prov_name})"
        if prov_name:
            province = prov_name

    if location and province:
        return location, province

    if url:
        m = re.search(r"/(?:venta|alquiler)-de-naves-industriales-en-([^/]+)/", url)
        if m:
            parts = m.group(1).rsplit("-", 1)
            if len(parts) == 2:
                if not province:
                    province = parts[1].replace("-", " ").title()
                if not location:
                    location = parts[0].replace("-", " ").title() + " (" + province + ")"

    if not location:
        for selector in [
            "[class*='location']",
            "[class*='Location']",
            "[data-testid='ad-location']",
            "[class*='ubicacion']",
            "span[class*='localidad']",
        ]:
            tag = soup.select_one(selector)
            if tag:
                location = tag.get_text(strip=True) or None
                break

    if not province:
        for a in soup.select("a[href*='naves-industriales-en-']"):
            href = a.get("href", "")
            m = re.search(r"naves-industriales-en-([^/]+)/$", href)
            if m:
                province = m.group(1).replace("-", " ").title()
                break

    return location, province


def parse_coordinates(ad_json: dict | None) -> tuple[float | None, float | None]:
    """Devuelve (latitude, longitude) desde el JSON."""
    if not ad_json:
        return None, None
    geo = ad_json.get("location", {}).get("geolocation", {})
    return geo.get("latitude"), geo.get("longitude")


def parse_address(shop_json: dict | None, soup: BeautifulSoup | None = None) -> str | None:
    """Extrae la dirección completa del vendedor."""
    if shop_json:
        parts = []
        addr = shop_json.get("address", "")
        if addr and "null" not in addr.lower():
            parts.append(addr.strip())
        zipcode = shop_json.get("zipcode")
        if zipcode:
            parts.append(zipcode)
        locality = shop_json.get("locality")
        if locality:
            parts.append(locality)
        province = shop_json.get("province")
        if province and locality != province:
            parts.append(province)
        if parts:
            return ", ".join(p for p in parts if p)

    if soup:
        for selector in ["[class*='address']", "[class*='Address']", "[class*='direccion']"]:
            tag = soup.select_one(selector)
            if tag:
                text = tag.get_text(strip=True)
                if text:
                    return text
    return None


def parse_zipcode(shop_json: dict | None) -> str | None:
    if shop_json:
        return shop_json.get("zipcode") or None
    return None


# ── Phone(s) ────────────────────────────────────────────────────────────────

def parse_phone(soup: BeautifulSoup, shop_json: dict | None = None) -> str | None:
    """Extrae el teléfono si está visible (puede estar oculto tras JS)."""
    if shop_json:
        phone = shop_json.get("phone1") or shop_json.get("phone2")
        if phone:
            return str(phone)

    for selector in [
        "[class*='phone']",
        "[class*='Phone']",
        "[class*='telefono']",
        "[data-testid*='phone']",
        "a[href^='tel:']",
    ]:
        tag = soup.select_one(selector)
        if tag:
            href = tag.get("href", "")
            if href.startswith("tel:"):
                return href.replace("tel:", "").strip()
            text = tag.get_text(strip=True)
            if re.match(r"[+\d\s\-\(\)]{7,}", text):
                return text

    text = soup.get_text()
    match = re.search(r"(?<!\d)([6-9]\d{8}|\+34\s?[6-9]\d{8}|0034\s?[6-9]\d{8})(?!\d)", text)
    if match:
        return match.group(1).strip()

    return None


def parse_phone2(shop_json: dict | None) -> str | None:
    if shop_json:
        phone2 = shop_json.get("phone2")
        if phone2:
            return str(phone2)
    return None


# ── Seller (type + name + id + url) ─────────────────────────────────────────

def parse_seller_type(soup: BeautifulSoup, ad_json: dict | None = None) -> str | None:
    if ad_json:
        st = ad_json.get("sellerType", {})
        if st.get("isPrivate") is True:
            return "particular"
        val = st.get("value", "")
        if val in ("professional", "profesional"):
            return "profesional"
        if val == "private":
            return "particular"

    text_lower = soup.get_text().lower()
    for selector in ["[class*='seller']", "[class*='Seller']", "[class*='anunciante']"]:
        tag = soup.select_one(selector)
        if tag:
            t = tag.get_text(strip=True).lower()
            if "profesional" in t or "empresa" in t or "agencia" in t:
                return "profesional"
            if "particular" in t:
                return "particular"
    if "profesional" in text_lower or "inmobiliaria" in text_lower:
        return "profesional"
    if "particular" in text_lower:
        return "particular"
    return None


def parse_seller_name(
    soup: BeautifulSoup,
    shop_json: dict | None = None,
    ad_json: dict | None = None,
) -> str | None:
    if shop_json:
        name = shop_json.get("name")
        if name:
            return name

    if ad_json:
        name = ad_json.get("author", {}).get("userName")
        if name:
            return name

    for selector in [
        ".ma-UserOverviewProfileName",
        "h2.ma-UserOverviewProfileName",
        "[class*='UserOverviewProfileName']",
        "[class*='seller-name']",
        "[class*='SellerName']",
        "[class*='nombre-anunciante']",
        "[data-testid='seller-name']",
    ]:
        tag = soup.select_one(selector)
        if tag:
            return tag.get_text(strip=True) or None
    return None


def parse_seller_id(ad_json: dict | None) -> str | None:
    if ad_json:
        return ad_json.get("author", {}).get("id")
    return None


def parse_seller_url(shop_json: dict | None) -> str | None:
    if shop_json:
        url = shop_json.get("url")
        if url:
            return "https://www.milanuncios.com" + url if url.startswith("/") else url
    return None


# ── Photos ──────────────────────────────────────────────────────────────────

def parse_photos(soup: BeautifulSoup, ad_json: dict | None = None) -> list[str]:
    """Extrae TODAS las URLs de imágenes del anuncio."""
    urls: set[str] = set()

    if ad_json:
        for img_url in ad_json.get("images", []):
            if img_url and isinstance(img_url, str):
                urls.add(img_url + "?rule=detail_640x480")

    for meta in soup.find_all("meta", property="og:image"):
        content = meta.get("content", "")
        if content and "milanuncios" in content:
            urls.add(content)

    for img in soup.find_all("img"):
        for attr in ("src", "data-src", "data-lazy-src", "data-original",
                     "data-zoom", "data-full", "data-image", "data-url"):
            src = img.get(attr, "")
            if src and "milanuncios" in src and not src.endswith(".svg"):
                src = re.sub(r"_\d+x\d+\.", ".", src)
                urls.add(src)

    for source in soup.find_all("source"):
        srcset = source.get("srcset", "")
        for part in srcset.split(","):
            part = part.strip().split(" ")[0]
            if part and "milanuncios" in part:
                urls.add(part)

    for tag in soup.find_all(style=True):
        matches = re.findall(r'url\(["\']?(https?://[^"\'>\s]+)["\']?\)', tag["style"])
        for m in matches:
            if "milanuncios" in m:
                urls.add(m)

    return sorted(urls)


# ── Dates ───────────────────────────────────────────────────────────────────

def parse_dates(
    soup: BeautifulSoup, ad_json: dict | None = None,
) -> tuple[str | None, str | None]:
    """Devuelve (published_at, updated_at) como strings ISO o texto libre."""
    published = None
    updated = None

    if ad_json:
        published = ad_json.get("publicationDate") or ad_json.get("sortDate")
        updated = ad_json.get("updateDate")
        if published and updated:
            return published, updated

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, dict):
                published = published or data.get("datePublished") or data.get("uploadDate")
                updated = updated or data.get("dateModified")
        except Exception:
            pass

    for meta in soup.find_all("meta"):
        prop = (meta.get("property", "") + meta.get("name", "")).lower()
        content = meta.get("content", "")
        if not published and ("published" in prop or ("date" in prop and "modified" not in prop)):
            published = content or None
        if not updated and ("modified" in prop or "updated" in prop):
            updated = content or None

    for selector in ["[class*='date']", "[class*='Date']", "[class*='fecha']", "time"]:
        for tag in soup.select(selector):
            dt = tag.get("datetime") or tag.get_text(strip=True)
            if dt and re.search(r"\d{2,4}", dt):
                if not published:
                    published = dt
                elif not updated:
                    updated = dt
                break

    return published, updated


# ── Property type + reference + structural attributes ──────────────────────

def parse_property_type(url: str, ad_json: dict | None = None) -> str | None:
    """Extrae el tipo de inmueble (nave industrial, local, almacén, etc.)."""
    if ad_json:
        categories = ad_json.get("categories", [])
        if len(categories) >= 2:
            return categories[1].get("name")
        if categories:
            return categories[0].get("name")

    if "naves-industriales" in url:
        return "Naves Industriales"
    if "locales-comerciales" in url:
        return "Locales Comerciales"
    if "almacenes" in url:
        return "Almacenes"

    return None


def parse_reference(soup: BeautifulSoup, ad_json: dict | None = None) -> str | None:
    """Extrae la referencia interna del vendedor (ej: 'FRRE-00104')."""
    desc = ""
    if ad_json:
        desc = ad_json.get("description", "") or ""
    if not desc:
        desc = soup.get_text()

    m = re.search(r"[Rr]ef(?:erencia)?[:\s.]+([A-Za-z0-9\-]{4,20})", desc)
    if m:
        return m.group(1).strip()

    for selector in [
        ".ma-AdDetail-description-reference",
        "[class*='reference']",
        "[class*='referencia']",
    ]:
        tag = soup.select_one(selector)
        if tag:
            text = tag.get_text(strip=True)
            if text:
                return text

    return None


def parse_rooms(soup: BeautifulSoup, ad_json: dict | None = None) -> int | None:
    if ad_json:
        rooms = ad_json.get("rooms") or ad_json.get("bedrooms")
        if rooms is not None:
            try:
                return int(rooms)
            except (ValueError, TypeError):
                pass

    text = soup.get_text()
    match = re.search(r"(\d+)\s*(habitaci[oó]n|dormitorio|cuarto)", text, re.IGNORECASE)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
    return None


def parse_bathrooms(soup: BeautifulSoup, ad_json: dict | None = None) -> int | None:
    if ad_json:
        baths = ad_json.get("bathrooms")
        if baths is not None:
            try:
                v = int(baths)
                return v if v > 0 else None
            except (ValueError, TypeError):
                pass

    text = soup.get_text()
    match = re.search(r"(\d+)\s*(ba[ñn]o|aseo|wc)", text, re.IGNORECASE)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
    return None


def parse_floor(soup: BeautifulSoup) -> str | None:
    text = soup.get_text()
    match = re.search(r"(planta\s*\w+|bajo|[0-9]+[aáºo]\s*planta)", text, re.IGNORECASE)
    if match:
        return match.group(0).strip()
    return None


def parse_condition(soup: BeautifulSoup, ad_json: dict | None = None) -> str | None:
    """Detecta si el inmueble es nuevo o de segunda mano."""
    if ad_json:
        condition = ad_json.get("condition")
        if condition:
            return condition

    text = soup.get_text().lower()
    if "segunda mano" in text or "2ª mano" in text:
        return "segunda mano"
    if "nuevo" in text or "obra nueva" in text:
        return "nuevo"

    for img in soup.find_all("img", alt=True):
        alt = img.get("alt", "").lower()
        if "segunda mano" in alt:
            return "segunda mano"
        if "nuevo" in alt:
            return "nuevo"

    return None


def parse_energy_certificate(soup: BeautifulSoup, ad_json: dict | None = None) -> str | None:
    """Extrae la calificación energética (A/B/C/D/E/F/G o 'en trámite')."""
    if ad_json:
        for attr in ad_json.get("attributes", []):
            t = attr.get("type", "")
            if "energ" in t.lower() or "certificado" in t.lower():
                return attr.get("valueFormatted") or attr.get("value")

    text = soup.get_text()
    m = re.search(
        r"certificad[oa]\s*energ[eé]tic[oa][:\s]+([A-Ga-g]|en\s*tr[aá]mite)",
        text, re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()

    m = re.search(r"[Ee]nerg[eé]tic[oa][^A-Za-z]{0,10}([A-Ga-g])\b", text)
    if m:
        return m.group(1).upper()

    return None


_FEATURE_SKIP_KEYWORDS = ("m²", "€/m", "metros", "superficie", "precio", "bath", "room", "habitac")


def parse_features(soup: BeautifulSoup, ad_json: dict | None = None) -> list[str]:
    """Extrae lista de características/amenidades del inmueble."""
    features: list[str] = []

    if ad_json:
        for tag in ad_json.get("tags", []):
            text = tag.get("text") or tag.get("type") or ""
            tag_type = tag.get("type", "").lower()
            if any(k in tag_type or k in text.lower() for k in _FEATURE_SKIP_KEYWORDS):
                continue
            if text:
                features.append(text)
        for extra in ad_json.get("extras", []):
            text = extra.get("text") or extra.get("type") or extra.get("name")
            if text:
                features.append(text)
        for la in ad_json.get("legalAttributes", []):
            text = la.get("text") or la.get("value")
            if text:
                features.append(text)

    for selector in [
        "[class*='features'] li",
        "[class*='characteristics'] li",
        "[class*='extras'] li",
        "[class*='amenities'] li",
        "[class*='Extras'] li",
    ]:
        for tag in soup.select(selector):
            text = tag.get_text(strip=True)
            if text and text not in features and not any(k in text.lower() for k in _FEATURE_SKIP_KEYWORDS):
                features.append(text)

    return list(dict.fromkeys(features))  # dedup preserving order
