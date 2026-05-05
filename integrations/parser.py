"""Top-level parser entry point + backward-compat re-exports.

Codex review R1: the original ~1000-line `parser.py` has been split into
focused submodules. This file is now the public surface — every external
caller can keep `from integrations.parser import …` unchanged because
all public names are re-exported here.

Submodules:
  - parser_core      JSON extraction primitives (parse_initial_props_json)
  - parser_fields    Individual field parsers (title, price, location, …)
  - parser_ad_type   4-layer venta/alquiler/dual cascade + keyword tables

`parse_listing_page` lives here because it's the orchestrator that pulls
every parser together — moving it would only push the import graph
deeper without making it clearer.
"""
from __future__ import annotations

import logging

from bs4 import BeautifulSoup

from integrations.parser_ad_type import (  # noqa: F401  (re-exported)
    _scan_text_for_ad_type,
    parse_ad_type,
)
from integrations.parser_core import (  # noqa: F401  (re-exported)
    _get_attribute_value,
    parse_initial_props_json,
)
from integrations.parser_fields import (  # noqa: F401  (re-exported)
    parse_address,
    parse_bathrooms,
    parse_condition,
    parse_coordinates,
    parse_dates,
    parse_description,
    parse_energy_certificate,
    parse_features,
    parse_floor,
    parse_listing_id,
    parse_location,
    parse_phone,
    parse_phone2,
    parse_photos,
    parse_price,
    parse_price_numeric,
    parse_price_per_m2,
    parse_property_type,
    parse_reference,
    parse_rooms,
    parse_seller_id,
    parse_seller_name,
    parse_seller_type,
    parse_seller_url,
    parse_surface,
    parse_title,
    parse_zipcode,
)

logger = logging.getLogger(__name__)


def parse_listing_page(url: str, html: str) -> dict:
    """Parse a full MilAnuncios listing page into a dict ready for `db.insert_listing`."""
    soup = BeautifulSoup(html, "html.parser")

    props = parse_initial_props_json(html)
    if not props:
        # Codex review B4: silent failure path. Without __INITIAL_PROPS__
        # the row will land in the DB with a recovered listing_id but
        # almost every other field empty. Surface this as a WARNING so
        # the dashboard log shows the page-structure regression instead
        # of pretending the scrape succeeded.
        logger.warning(
            "[parser] __INITIAL_PROPS__ not found for %s — most fields "
            "will be empty (page blocked, A/B test, or layout change)",
            url,
        )
    ad = props.get("ad", {})
    shop = props.get("shop", {})

    location, province = parse_location(soup, url, ad_json=ad)
    latitude, longitude = parse_coordinates(ad)
    published_at, updated_at = parse_dates(soup, ad_json=ad)

    price_numeric = parse_price_numeric(ad)
    surface_m2 = parse_surface(soup, ad_json=ad)
    price_per_m2 = parse_price_per_m2(ad, soup)

    # Calcular price_per_m2 como fallback si no está en la página
    if price_per_m2 is None and price_numeric and surface_m2 and surface_m2 > 0:
        price_per_m2 = int(price_numeric * 100 / surface_m2) / 100.0

    # Codex review B5: cache title/description so parse_ad_type's
    # body-scan (capa 4) doesn't re-traverse the BeautifulSoup tree.
    title = parse_title(soup)
    description = parse_description(soup, ad_json=ad)

    return {
        "listing_id": ad.get("id") or parse_listing_id(url),
        "url": url,
        "reference": parse_reference(soup, ad_json=ad),

        "title": title,
        "description": description,

        "price": parse_price(soup, ad_json=ad),
        "price_numeric": price_numeric,
        "price_per_m2": price_per_m2,

        "surface_m2": surface_m2,
        "rooms": parse_rooms(soup, ad_json=ad),
        "bathrooms": parse_bathrooms(soup, ad_json=ad),
        "floor": parse_floor(soup),
        "condition": parse_condition(soup, ad_json=ad),
        "energy_certificate": parse_energy_certificate(soup, ad_json=ad),
        "features": parse_features(soup, ad_json=ad),

        "ad_type": parse_ad_type(
            url, ad_json=ad, title=title, description=description,
        ),
        "property_type": parse_property_type(url, ad_json=ad),

        "location": location,
        "province": province,
        "address": parse_address(shop, soup),
        "zipcode": parse_zipcode(shop),
        "latitude": latitude,
        "longitude": longitude,

        "seller_type": parse_seller_type(soup, ad_json=ad),
        "seller_name": parse_seller_name(soup, shop_json=shop, ad_json=ad),
        "seller_id": parse_seller_id(ad),
        "seller_url": parse_seller_url(shop),
        "phone": parse_phone(soup, shop_json=shop),
        "phone2": parse_phone2(shop),

        "photos": parse_photos(soup, ad_json=ad),

        "published_at": published_at,
        "updated_at": updated_at,

        "raw_html": html,
    }
