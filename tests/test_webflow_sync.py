"""Tests for webflow_sync.build_field_data field-level transformations.

Iteración 2026-05:
- latitude/longitude reach Webflow as PlainText (no Map composite).
- Generic loop preserves existing behaviour for Number/Date types.
- Source-url dedup index gracefully degrades when the schema lacks the field.
"""
import pytest

from integrations.webflow_sync import (
    FIELD_MAP_PATTERNS,
    _extract_listing_id,
    build_field_data,
    resolve_field_mapping,
)


class TestExtractListingId:
    """Regex extraction of MilAnuncios listing ID from URL."""

    def test_typical_url(self):
        url = "https://www.milanuncios.com/venta-de-naves-industriales-en-atarfe-granada/atarfe-591093579.htm"
        assert _extract_listing_id(url) == "591093579"

    def test_alquiler_url(self):
        url = "https://www.milanuncios.com/alquiler-de-naves-industriales-en-montornes-del-valles-barcelona/montornes-del-valles-583152242.htm"
        assert _extract_listing_id(url) == "583152242"

    def test_missing_id_returns_none(self):
        assert _extract_listing_id("https://www.milanuncios.com/naves/foo.htm") is None

    def test_empty_string_returns_none(self):
        assert _extract_listing_id("") is None

    def test_none_returns_none(self):
        assert _extract_listing_id(None) is None

    def test_non_milanuncios_url_with_id_still_matches(self):
        assert _extract_listing_id("https://example.com/x-12345.htm") == "12345"


COLLECTION_FIELDS_PLAINTEXT_LAT_LNG = [
    {"slug": "name",      "type": "PlainText", "isRequired": True},
    {"slug": "slug",      "type": "PlainText", "isRequired": True},
    {"slug": "latitude",  "type": "PlainText"},
    {"slug": "longitude", "type": "PlainText"},
    {"slug": "new-sale-price", "type": "PlainText"},
]


class TestLatitudeLongitudeMapping:
    def test_field_map_patterns_includes_lat_lng(self):
        assert "latitude" in FIELD_MAP_PATTERNS
        assert "longitude" in FIELD_MAP_PATTERNS
        assert "latitude" in FIELD_MAP_PATTERNS["latitude"]
        assert "longitude" in FIELD_MAP_PATTERNS["longitude"]

    def test_resolve_mapping_finds_lat_lng_when_present(self):
        schema = {"fields": COLLECTION_FIELDS_PLAINTEXT_LAT_LNG}
        mapping = resolve_field_mapping(schema)
        assert mapping.get("latitude") == "latitude"
        assert mapping.get("longitude") == "longitude"

    def test_lat_lng_serialized_as_plaintext_strings(self):
        row = {
            "listing_id": "1",
            "title": "Test",
            "webflow_slug": "test",
            "latitude": 40.4168,
            "longitude": -3.7038,
        }
        mapping = {"title": "name", "latitude": "latitude", "longitude": "longitude"}
        out = build_field_data(row, mapping, [], COLLECTION_FIELDS_PLAINTEXT_LAT_LNG)
        # PlainText → str(float) preserved with full precision
        assert out["latitude"] == "40.4168"
        assert out["longitude"] == "-3.7038"

    def test_lat_lng_omitted_when_none(self):
        row = {"listing_id": "2", "title": "T", "webflow_slug": "t", "latitude": None, "longitude": None}
        mapping = {"title": "name", "latitude": "latitude", "longitude": "longitude"}
        out = build_field_data(row, mapping, [], COLLECTION_FIELDS_PLAINTEXT_LAT_LNG)
        assert "latitude" not in out
        assert "longitude" not in out


class TestContactFieldsMapping:
    """Iteración 2026-05 follow-up: Benedict added `contact-name` and
    `contact-number` to the Webflow collection. They now own seller_name and
    phone respectively, replacing the previously unmapped Spanish slugs."""

    SCHEMA = [
        {"slug": "name",           "type": "PlainText", "isRequired": True},
        {"slug": "slug",           "type": "PlainText", "isRequired": True},
        {"slug": "contact-name",   "type": "PlainText"},
        {"slug": "contact-number", "type": "PlainText"},
    ]

    def test_seller_name_maps_to_contact_name(self):
        mapping = resolve_field_mapping({"fields": self.SCHEMA})
        assert mapping.get("seller_name") == "contact-name"

    def test_phone_maps_to_contact_number(self):
        mapping = resolve_field_mapping({"fields": self.SCHEMA})
        assert mapping.get("phone") == "contact-number"

    def test_seller_name_and_phone_serialized(self):
        row = {
            "listing_id": "1",
            "title": "Test",
            "webflow_slug": "test",
            "seller_name": "Inmobiliaria Acme",
            "phone": "+34 600 111 222",
        }
        mapping = {
            "title": "name",
            "seller_name": "contact-name",
            "phone": "contact-number",
        }
        out = build_field_data(row, mapping, [], self.SCHEMA)
        assert out["contact-name"] == "Inmobiliaria Acme"
        assert out["contact-number"] == "+34 600 111 222"


class TestUrlFieldPrecedence:
    """Live Webflow schema now exposes `source` (PlainText). `google-place-id`
    is kept in the candidate list as a transitional fallback for items not
    yet migrated by scripts/migrate_url_to_source.py."""

    SCHEMA_WITH_SOURCE = [
        {"slug": "name",            "type": "PlainText", "isRequired": True},
        {"slug": "slug",            "type": "PlainText", "isRequired": True},
        {"slug": "google-place-id", "type": "PlainText"},
        {"slug": "source",          "type": "PlainText"},
    ]

    SCHEMA_LEGACY = [
        {"slug": "name",            "type": "PlainText", "isRequired": True},
        {"slug": "slug",            "type": "PlainText", "isRequired": True},
        {"slug": "google-place-id", "type": "PlainText"},
    ]

    def test_url_prefers_source_when_present(self):
        mapping = resolve_field_mapping({"fields": self.SCHEMA_WITH_SOURCE})
        assert mapping.get("url") == "source"

    def test_url_falls_back_to_google_place_id_when_source_missing(self):
        mapping = resolve_field_mapping({"fields": self.SCHEMA_LEGACY})
        assert mapping.get("url") == "google-place-id"

    def test_listing_url_lands_on_source(self):
        row = {
            "listing_id": "1",
            "title": "T",
            "webflow_slug": "t",
            "url": "https://www.milanuncios.com/naves/foo-123.htm",
        }
        mapping = {"title": "name", "url": "source"}
        out = build_field_data(row, mapping, [], self.SCHEMA_WITH_SOURCE)
        assert out["source"] == "https://www.milanuncios.com/naves/foo-123.htm"


class TestNumberFieldStillFloat:
    """Regression: existing Number-type fields still get float() conversion."""

    def test_number_field_converted_to_float(self):
        schema_fields = [
            {"slug": "name", "type": "PlainText", "isRequired": True},
            {"slug": "squared-meters", "type": "Number"},
        ]
        row = {"listing_id": "3", "title": "T", "webflow_slug": "t", "surface_m2": 1200}
        mapping = {"title": "name", "surface_m2": "squared-meters"}
        out = build_field_data(row, mapping, [], schema_fields)
        assert out["squared-meters"] == 1200.0
        assert isinstance(out["squared-meters"], float)


# ─── Iteración 2026-05, Tarea 5: precio formateado por tipo ────────────────────
COLLECTION_FIELDS_WITH_PRICE = [
    {"slug": "name", "type": "PlainText", "isRequired": True},
    {"slug": "new-sale-price", "type": "PlainText"},
    {"slug": "new-price-sm2-month", "type": "PlainText"},
]


class TestPriceFormattingByAdType:
    def _row(self, **overrides):
        base = {
            "listing_id": "1",
            "title": "T",
            "webflow_slug": "t",
            "ad_type": None,
            "price_numeric": None,
            "price_per_m2": None,
        }
        base.update(overrides)
        return base

    def test_venta_uses_sale_price_field_with_es_format(self):
        row = self._row(ad_type="venta", price_numeric=199000)
        mapping = {"title": "name", "price_numeric": "new-sale-price"}
        out = build_field_data(row, mapping, [], COLLECTION_FIELDS_WITH_PRICE)
        assert out["new-sale-price"] == "199.000 €"
        assert "new-price-sm2-month" not in out

    def test_alquiler_uses_per_m2_field(self):
        row = self._row(ad_type="alquiler", price_per_m2=1.19)
        mapping = {"title": "name", "price_per_m2": "new-price-sm2-month"}
        out = build_field_data(row, mapping, [], COLLECTION_FIELDS_WITH_PRICE)
        assert out["new-price-sm2-month"] == "1.19€/m²"
        assert "new-sale-price" not in out

    def test_alquiler_falls_back_to_monthly_when_no_per_m2(self):
        row = self._row(ad_type="alquiler", price_numeric=1500)
        mapping = {"title": "name", "price_numeric": "new-sale-price"}
        out = build_field_data(row, mapping, [], COLLECTION_FIELDS_WITH_PRICE)
        # falls back to monthly total in the per-m2 slot
        assert out["new-price-sm2-month"] == "1.500 €/mes"
        assert "new-sale-price" not in out

    def test_venta_alquiler_routes_like_alquiler(self):
        # Dual offering: price-per-m² lands on the rental slot, sale slot empty.
        row = self._row(
            ad_type="venta_alquiler", price_numeric=1500, price_per_m2=1.66,
        )
        mapping = {
            "title": "name",
            "price_numeric": "new-sale-price",
            "price_per_m2": "new-price-sm2-month",
        }
        out = build_field_data(row, mapping, [], COLLECTION_FIELDS_WITH_PRICE)
        assert out["new-price-sm2-month"] == "1.66€/m²"
        assert "new-sale-price" not in out

    def test_unknown_ad_type_does_not_override_generic(self):
        row = self._row(ad_type=None, price_numeric=199000)
        mapping = {"title": "name", "price_numeric": "new-sale-price"}
        out = build_field_data(row, mapping, [], COLLECTION_FIELDS_WITH_PRICE)
        # generic str() conversion happens in the loop, no override
        assert out["new-sale-price"] == "199000"


# ─── Iteración 2026-05, Tarea 4: descripción RichText ──────────────────────────
class TestDescriptionRichTextConversion:
    SCHEMA = [
        {"slug": "name", "type": "PlainText", "isRequired": True},
        {"slug": "funeral-home-biography", "type": "RichText"},
    ]

    def test_richtext_field_gets_html(self):
        row = {
            "listing_id": "1",
            "title": "T",
            "webflow_slug": "t",
            "description": "Linea uno\n\nLinea dos.",
        }
        mapping = {"title": "name", "description": "funeral-home-biography"}
        out = build_field_data(row, mapping, [], self.SCHEMA)
        assert out["funeral-home-biography"] == "<p>Linea uno</p><p>Linea dos.</p>"

    def test_plaintext_description_field_unchanged(self):
        # Sanity: if the description field is PlainText (legacy), we keep raw
        schema = [
            {"slug": "name", "type": "PlainText", "isRequired": True},
            {"slug": "description", "type": "PlainText"},
        ]
        row = {"listing_id": "2", "title": "T", "webflow_slug": "t", "description": "Una linea."}
        mapping = {"title": "name", "description": "description"}
        out = build_field_data(row, mapping, [], schema)
        assert out["description"] == "Una linea."  # NOT converted to HTML


# ─── Iteración 2026-05, Tarea 3: dedup + split de imágenes ────────────────────
COLLECTION_FIELDS_FULL_IMAGES = [
    {"slug": "name", "type": "PlainText", "isRequired": True},
    {"slug": "main-image", "type": "Image"},
    {"slug": "listing-images", "type": "MultiImage"},
    {"slug": "all-images", "type": "MultiImage"},
    {"slug": "additional-images", "type": "MultiImage"},
]


class TestImageSplitting:
    def _row(self):
        return {"listing_id": "1", "title": "T", "webflow_slug": "t"}

    def test_dedup_preserves_order(self):
        urls = ["a", "b", "a", "c", "b", "d"]
        out = build_field_data(self._row(), {"title": "name"}, urls, COLLECTION_FIELDS_FULL_IMAGES)
        # main = a (first); top4 = b,c,d (3 items, since only 4 unique)
        assert out["main-image"]["url"] == "a"
        listing_urls = [i["url"] for i in out["listing-images"]]
        assert listing_urls == ["b", "c", "d"]

    def test_main_is_first_image(self):
        urls = [f"u{i}" for i in range(8)]
        out = build_field_data(self._row(), {"title": "name"}, urls, COLLECTION_FIELDS_FULL_IMAGES)
        assert out["main-image"]["url"] == "u0"

    def test_listing_images_holds_2_to_5(self):
        urls = [f"u{i}" for i in range(8)]
        out = build_field_data(self._row(), {"title": "name"}, urls, COLLECTION_FIELDS_FULL_IMAGES)
        listing_urls = [i["url"] for i in out["listing-images"]]
        assert listing_urls == ["u1", "u2", "u3", "u4"]

    def test_all_images_holds_main_plus_top4(self):
        urls = [f"u{i}" for i in range(8)]
        out = build_field_data(self._row(), {"title": "name"}, urls, COLLECTION_FIELDS_FULL_IMAGES)
        airbnb = [i["url"] for i in out["all-images"]]
        assert airbnb == ["u0", "u1", "u2", "u3", "u4"]

    def test_additional_images_holds_overflow(self):
        urls = [f"u{i}" for i in range(8)]
        out = build_field_data(self._row(), {"title": "name"}, urls, COLLECTION_FIELDS_FULL_IMAGES)
        additional = [i["url"] for i in out["additional-images"]]
        assert additional == ["u5", "u6", "u7"]

    def test_additional_images_omitted_when_no_overflow(self):
        urls = [f"u{i}" for i in range(3)]  # only 3 images, no overflow
        out = build_field_data(self._row(), {"title": "name"}, urls, COLLECTION_FIELDS_FULL_IMAGES)
        assert "additional-images" not in out

    def test_alt_text_uses_listing_name(self):
        urls = ["a", "b"]
        row = {"listing_id": "9", "title": "Mi nave", "webflow_slug": "mi-nave"}
        out = build_field_data(row, {"title": "name"}, urls, COLLECTION_FIELDS_FULL_IMAGES)
        assert out["main-image"]["alt"] == "Mi nave"
        assert out["listing-images"][0]["alt"] == "Mi nave"

    def test_no_images_omits_all_image_fields(self):
        out = build_field_data(self._row(), {"title": "name"}, [], COLLECTION_FIELDS_FULL_IMAGES)
        for slug in ("main-image", "listing-images", "all-images", "additional-images"):
            assert slug not in out

    def test_realistic_12_with_dups(self):
        # 12 with 3 dups → 9 unique. main=u1, top4=u2..u5, all-images=u1..u5, additional=u6..u9
        urls = ["u1", "u2", "u1", "u3", "u4", "u5", "u3", "u6", "u7", "u8", "u9", "u2"]
        out = build_field_data(self._row(), {"title": "name"}, urls, COLLECTION_FIELDS_FULL_IMAGES)
        assert out["main-image"]["url"] == "u1"
        assert [i["url"] for i in out["listing-images"]] == ["u2", "u3", "u4", "u5"]
        assert [i["url"] for i in out["all-images"]] == ["u1", "u2", "u3", "u4", "u5"]
        assert [i["url"] for i in out["additional-images"]] == ["u6", "u7", "u8", "u9"]


# ─── Iteración 2026-05, Tarea 6: source-url dedup index ───────────────────────
class _StubClient:
    def __init__(self, items=None, raise_exc=None):
        self._items = items or []
        self._raise = raise_exc

    async def list_items(self, *_, **__):
        if self._raise:
            raise self._raise
        return self._items


class TestBuildSourceUrlIndex:
    @pytest.mark.asyncio
    async def test_empty_when_field_not_mapped(self):
        # If the schema has no `url` mapping, we skip the index entirely.
        index = await _build_source_url_index(_StubClient(), {}, None)
        assert index == {}

    @pytest.mark.asyncio
    async def test_returns_url_to_item_id_map(self):
        items = [
            {"id": "abc1", "fieldData": {"source-url": "https://example.com/1"}},
            {"id": "abc2", "fieldData": {"source-url": "https://example.com/2"}},
            {"id": "abc3", "fieldData": {}},  # no source url
        ]
        index = await _build_source_url_index(
            _StubClient(items), {"url": "source-url"}, None,
        )
        assert index == {
            "https://example.com/1": "abc1",
            "https://example.com/2": "abc2",
        }

    @pytest.mark.asyncio
    async def test_failure_returns_empty_does_not_raise(self):
        client = _StubClient(raise_exc=RuntimeError("API down"))
        index = await _build_source_url_index(
            client, {"url": "source-url"}, None,
        )
        assert index == {}
