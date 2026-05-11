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

    def test_url_with_query_string(self):
        url = "https://www.milanuncios.com/x/atarfe-591093579.htm?utm_source=feed"
        assert _extract_listing_id(url) == "591093579"

    def test_url_with_fragment(self):
        url = "https://www.milanuncios.com/x/atarfe-591093579.htm#gallery"
        assert _extract_listing_id(url) == "591093579"


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


import asyncio
from unittest.mock import AsyncMock

from integrations.webflow_sync import (
    _build_dedup_indices,
    _make_composite_key,
    _normalize_title,
)


class TestNormalizeTitle:
    """Title normalization: lowercase, drop punctuation, collapse whitespace."""

    def test_lowercases(self):
        assert _normalize_title("Nave Industrial") == "nave industrial"

    def test_strips_punctuation(self):
        assert _normalize_title("Nave en Atarfe, Granada.") == "nave en atarfe granada"

    def test_collapses_whitespace(self):
        assert _normalize_title("Nave    industrial\n\ten   Atarfe") == "nave industrial en atarfe"

    def test_keeps_unicode_letters(self):
        # Spanish accents are word chars under re.UNICODE — preserved.
        assert _normalize_title("Nave en Montornés") == "nave en montornés"

    def test_empty_input(self):
        assert _normalize_title("") == ""
        assert _normalize_title(None) == ""
        assert _normalize_title("   ") == ""


class TestMakeCompositeKey:
    """Composite key fuses normalized title with 4-decimal lat/lng."""

    def test_typical_case(self):
        key = _make_composite_key(
            "Nave industrial en Atarfe (Granada)", 37.212919714, -3.698543688,
        )
        assert key == "nave industrial en atarfe granada|37.2129|-3.6985"

    def test_string_coordinates_parsed(self):
        # Webflow stores latitude/longitude as PlainText — values arrive
        # as strings from list_items.
        key = _make_composite_key("Nave", "41.560394", "2.270845")
        assert key == "nave|41.5604|2.2708"

    def test_returns_none_when_title_missing(self):
        assert _make_composite_key("", 1.0, 2.0) is None
        assert _make_composite_key(None, 1.0, 2.0) is None

    def test_returns_none_when_lat_missing(self):
        assert _make_composite_key("Nave", None, 2.0) is None
        assert _make_composite_key("Nave", "", 2.0) is None

    def test_returns_none_when_lng_missing(self):
        assert _make_composite_key("Nave", 1.0, None) is None

    def test_returns_none_when_coords_non_numeric(self):
        assert _make_composite_key("Nave", "not-a-number", 2.0) is None
        assert _make_composite_key("Nave", 1.0, "junk") is None

    def test_geocoder_jitter_within_11m_collapses(self):
        # Two coords differing only in the 5th decimal collapse to the
        # same 4-decimal key — geocoder jitter doesn't break dedup.
        # (Avoiding the .5 half-step where banker's rounding diverges.)
        k1 = _make_composite_key("Nave A", 41.56041, 2.27081)
        k2 = _make_composite_key("Nave A", 41.56043, 2.27083)
        assert k1 == k2

    def test_adjacent_warehouses_at_4th_decimal_distinct(self):
        # Coords differing in the 4th decimal (~11m apart) produce
        # distinct keys — different warehouses on the same street remain
        # distinguishable.
        k1 = _make_composite_key("Nave en Calle X", 41.5604, 2.2708)
        k2 = _make_composite_key("Nave en Calle X", 41.5605, 2.2708)
        assert k1 != k2


class TestBuildDedupIndices:
    """_build_dedup_indices returns (listing_id_index, composite_index)
    from a single pass over CMS items."""

    def _make_client(self, items):
        client = AsyncMock()
        client.list_items = AsyncMock(return_value=items)
        return client

    def _full_mapping(self) -> dict[str, str]:
        return {
            "url": "source",
            "title": "name",
            "latitude": "latitude",
            "longitude": "longitude",
        }

    def test_indexes_items_by_listing_id(self):
        items = [
            {"id": "item-a", "fieldData": {"source": "https://www.milanuncios.com/x/foo-111.htm"}},
            {"id": "item-b", "fieldData": {"source": "https://www.milanuncios.com/x/bar-222.htm"}},
        ]
        client = self._make_client(items)
        lid_idx, comp_idx = asyncio.run(_build_dedup_indices(client, {"url": "source"}, None))
        assert lid_idx == {"111": "item-a", "222": "item-b"}
        assert comp_idx == {}  # no title/coords mapped

    def test_indexes_items_by_composite(self):
        items = [
            {"id": "item-a", "fieldData": {
                "source": "https://www.milanuncios.com/x/foo-111.htm",
                "name": "Nave en Atarfe",
                "latitude": "37.2129",
                "longitude": "-3.6985",
            }},
        ]
        client = self._make_client(items)
        lid_idx, comp_idx = asyncio.run(_build_dedup_indices(client, self._full_mapping(), None))
        assert lid_idx == {"111": "item-a"}
        assert comp_idx == {"nave en atarfe|37.2129|-3.6985": "item-a"}

    def test_skips_composite_when_coords_missing(self):
        items = [
            {"id": "item-a", "fieldData": {
                "source": "https://www.milanuncios.com/x/foo-111.htm",
                "name": "Nave sin coords",
                "latitude": "",
                "longitude": "",
            }},
        ]
        client = self._make_client(items)
        lid_idx, comp_idx = asyncio.run(_build_dedup_indices(client, self._full_mapping(), None))
        assert lid_idx == {"111": "item-a"}
        assert comp_idx == {}

    def test_skips_non_url_values(self):
        items = [
            {"id": "item-a", "fieldData": {"source": "ChIJN1t_tDeuEmsRUsoyG83frY4"}},
            {"id": "item-b", "fieldData": {"source": "https://www.milanuncios.com/x/foo-333.htm"}},
        ]
        client = self._make_client(items)
        lid_idx, _ = asyncio.run(_build_dedup_indices(client, {"url": "source"}, None))
        assert lid_idx == {"333": "item-b"}

    def test_skips_urls_without_listing_id(self):
        items = [
            {"id": "item-a", "fieldData": {"source": "https://www.milanuncios.com/naves/"}},
            {"id": "item-b", "fieldData": {"source": "https://www.milanuncios.com/x/foo-444.htm"}},
        ]
        client = self._make_client(items)
        lid_idx, _ = asyncio.run(_build_dedup_indices(client, {"url": "source"}, None))
        assert lid_idx == {"444": "item-b"}

    def test_returns_empty_when_no_dedup_keys_mappable(self):
        client = self._make_client([])
        lid_idx, comp_idx = asyncio.run(_build_dedup_indices(client, {}, None))
        assert lid_idx == {} and comp_idx == {}

    def test_returns_empty_when_list_items_fails(self):
        client = AsyncMock()
        client.list_items = AsyncMock(side_effect=RuntimeError("network"))
        lid_idx, comp_idx = asyncio.run(_build_dedup_indices(client, self._full_mapping(), None))
        assert lid_idx == {} and comp_idx == {}

    def test_composite_built_even_when_no_url_slug(self):
        # Defensive: if `source` is somehow not mapped but title+coords are,
        # composite-only dedup still works.
        items = [
            {"id": "item-a", "fieldData": {
                "name": "Nave en Atarfe",
                "latitude": "37.2129",
                "longitude": "-3.6985",
            }},
        ]
        client = self._make_client(items)
        mapping = {"title": "name", "latitude": "latitude", "longitude": "longitude"}
        lid_idx, comp_idx = asyncio.run(_build_dedup_indices(client, mapping, None))
        assert lid_idx == {}
        assert comp_idx == {"nave en atarfe|37.2129|-3.6985": "item-a"}


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


# (TestBuildSourceUrlIndex removed 2026-05-10 — superseded by
# TestDedupIndexByListingId above. The renamed function
# _build_listing_id_index returns {listing_id: item_id} instead of
# {url: item_id}; the old URL-keyed behavior no longer exists.)


from unittest.mock import patch, MagicMock

from integrations.webflow_sync import sync_pending_listings


class TestSyncSkipsExistingListingId:
    """E2E: when a pending DB row's listing_id already exists in the CMS,
    sync adopts the existing item_id and skips creation."""

    def test_existing_listing_id_short_circuits_creation(self, monkeypatch):
        pending_row = {
            "listing_id": "999",
            "url": "https://www.milanuncios.com/x/foo-999.htm",
            "title": "Test Warehouse",
            "webflow_slug": "test-warehouse",
        }

        existing_cms_item = {
            "id": "wf-item-existing",
            "fieldData": {"source": "https://www.milanuncios.com/x/foo-999.htm"},
        }

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get_collection_schema = AsyncMock(return_value={
            "fields": [
                {"slug": "name",   "type": "PlainText", "isRequired": True},
                {"slug": "slug",   "type": "PlainText", "isRequired": True},
                {"slug": "source", "type": "PlainText"},
            ],
        })
        mock_client.list_items = AsyncMock(return_value=[existing_cms_item])
        mock_client.resolve_spanish_locale_id = AsyncMock(return_value=None)
        # Trip-wire: if creation ever runs, the test must fail loudly.
        mock_client.create_item_draft = AsyncMock(
            side_effect=AssertionError("create_item_draft must not be called"),
        )

        monkeypatch.setenv("WEBFLOW_TOKEN", "fake")
        monkeypatch.setenv("WEBFLOW_COLLECTION_ID", "fake")

        with patch("integrations.webflow_client.WEBFLOW_TOKEN", "fake"), \
             patch("integrations.webflow_client.COLLECTION_ID", "fake"), \
             patch("integrations.webflow_sync.get_unsynced_listings", return_value=[pending_row]), \
             patch("integrations.webflow_sync.update_webflow_id") as mock_update, \
             patch("integrations.webflow_sync.WebflowClient", return_value=mock_client), \
             patch("integrations.webflow_sync.sqlite3.connect", return_value=MagicMock()):

            result = asyncio.run(sync_pending_listings())

        assert result["synced"] == 1
        assert result["failed"] == 0
        mock_update.assert_called_once()
        called_args = mock_update.call_args[0]
        assert called_args[1] == "999"
        assert called_args[2] == "wf-item-existing"


class TestSyncSkipsRelistedByCompositeKey:
    """When a row has a NEW listing_id (re-listed) but the same physical
    warehouse already lives in the CMS (same normalized title + coords),
    the composite secondary key catches it."""

    def test_composite_match_short_circuits_creation(self, monkeypatch):
        # Pending row: a re-listing (new ID 999998) of the same warehouse
        # the CMS already has under ID 111111.
        pending_row = {
            "listing_id": "999998",
            "url": "https://www.milanuncios.com/x/atarfe-999998.htm",
            "title": "Nave industrial en Atarfe (Granada)",
            "latitude": 37.2129,
            "longitude": -3.6985,
            "webflow_slug": "nave-atarfe",
        }

        existing_cms_item = {
            "id": "wf-item-original",
            "fieldData": {
                "source": "https://www.milanuncios.com/x/atarfe-111111.htm",
                "name": "Nave industrial en Atarfe (Granada)",
                "latitude": "37.21290000",
                "longitude": "-3.69850001",
            },
        }

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get_collection_schema = AsyncMock(return_value={
            "fields": [
                {"slug": "name",      "type": "PlainText", "isRequired": True},
                {"slug": "slug",      "type": "PlainText", "isRequired": True},
                {"slug": "source",    "type": "PlainText"},
                {"slug": "latitude",  "type": "PlainText"},
                {"slug": "longitude", "type": "PlainText"},
            ],
        })
        mock_client.list_items = AsyncMock(return_value=[existing_cms_item])
        mock_client.resolve_spanish_locale_id = AsyncMock(return_value=None)
        mock_client.create_item = AsyncMock(
            side_effect=AssertionError("create_item must not be called for a re-listing"),
        )

        monkeypatch.setenv("WEBFLOW_TOKEN", "fake")
        monkeypatch.setenv("WEBFLOW_COLLECTION_ID", "fake")

        with patch("integrations.webflow_client.WEBFLOW_TOKEN", "fake"), \
             patch("integrations.webflow_client.COLLECTION_ID", "fake"), \
             patch("integrations.webflow_sync.get_unsynced_listings", return_value=[pending_row]), \
             patch("integrations.webflow_sync.update_webflow_id") as mock_update, \
             patch("integrations.webflow_sync.WebflowClient", return_value=mock_client), \
             patch("integrations.webflow_sync.sqlite3.connect", return_value=MagicMock()):

            result = asyncio.run(sync_pending_listings())

        assert result["synced"] == 1
        assert result["failed"] == 0
        mock_update.assert_called_once()
        called_args = mock_update.call_args[0]
        assert called_args[1] == "999998"            # new listing_id from DB row
        assert called_args[2] == "wf-item-original"  # adopted CMS id of the original

    def test_listing_id_takes_precedence_over_composite(self, monkeypatch):
        # When BOTH keys match different CMS items (edge case), listing_id
        # wins. This is deterministic and matches the order in the code.
        pending_row = {
            "listing_id": "555",
            "url": "https://www.milanuncios.com/x/foo-555.htm",
            "title": "Nave en X",
            "latitude": 40.0,
            "longitude": -3.0,
            "webflow_slug": "nave-x",
        }

        items = [
            # Matches by listing_id
            {"id": "wf-by-lid", "fieldData": {
                "source": "https://www.milanuncios.com/x/foo-555.htm",
                "name": "Different name",
                "latitude": "99.0",
                "longitude": "99.0",
            }},
            # Matches by composite
            {"id": "wf-by-composite", "fieldData": {
                "source": "https://www.milanuncios.com/x/other-9999.htm",
                "name": "Nave en X",
                "latitude": "40.0",
                "longitude": "-3.0",
            }},
        ]

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get_collection_schema = AsyncMock(return_value={
            "fields": [
                {"slug": "name",      "type": "PlainText", "isRequired": True},
                {"slug": "slug",      "type": "PlainText", "isRequired": True},
                {"slug": "source",    "type": "PlainText"},
                {"slug": "latitude",  "type": "PlainText"},
                {"slug": "longitude", "type": "PlainText"},
            ],
        })
        mock_client.list_items = AsyncMock(return_value=items)
        mock_client.resolve_spanish_locale_id = AsyncMock(return_value=None)
        mock_client.create_item_draft = AsyncMock(
            side_effect=AssertionError("create_item_draft must not be called"),
        )

        monkeypatch.setenv("WEBFLOW_TOKEN", "fake")
        monkeypatch.setenv("WEBFLOW_COLLECTION_ID", "fake")

        with patch("integrations.webflow_client.WEBFLOW_TOKEN", "fake"), \
             patch("integrations.webflow_client.COLLECTION_ID", "fake"), \
             patch("integrations.webflow_sync.get_unsynced_listings", return_value=[pending_row]), \
             patch("integrations.webflow_sync.update_webflow_id") as mock_update, \
             patch("integrations.webflow_sync.WebflowClient", return_value=mock_client), \
             patch("integrations.webflow_sync.sqlite3.connect", return_value=MagicMock()):

            asyncio.run(sync_pending_listings())

        called_args = mock_update.call_args[0]
        assert called_args[2] == "wf-by-lid"  # listing_id wins


class TestSyncCreatesItemWhenIndexEmpty:
    """Codex review NTH-4: when _build_dedup_indices returns empty (because
    list_items failed), the pending row falls through and IS created — no
    silent no-op."""

    def test_empty_index_does_not_skip_creation(self, monkeypatch):
        pending_row = {
            "listing_id": "777",
            "url": "https://www.milanuncios.com/x/foo-777.htm",
            "title": "Nave Test",
            "latitude": 40.0,
            "longitude": -3.0,
            "webflow_slug": "nave-test",
        }

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get_collection_schema = AsyncMock(return_value={
            "fields": [
                {"slug": "name",   "type": "PlainText", "isRequired": True},
                {"slug": "slug",   "type": "PlainText", "isRequired": True},
                {"slug": "source", "type": "PlainText"},
            ],
        })
        # list_items raises — indices come back empty.
        mock_client.list_items = AsyncMock(side_effect=RuntimeError("API down"))
        mock_client.resolve_spanish_locale_id = AsyncMock(return_value=None)
        mock_client.create_item_draft = AsyncMock(
            return_value={"id": "wf-newly-created", "isDraft": True},
        )

        monkeypatch.setenv("WEBFLOW_TOKEN", "fake")
        monkeypatch.setenv("WEBFLOW_COLLECTION_ID", "fake")

        with patch("integrations.webflow_client.WEBFLOW_TOKEN", "fake"), \
             patch("integrations.webflow_client.COLLECTION_ID", "fake"), \
             patch("integrations.webflow_sync.get_unsynced_listings", return_value=[pending_row]), \
             patch("integrations.webflow_sync.update_webflow_id"), \
             patch("integrations.webflow_sync.upload_listing_images",
                   AsyncMock(return_value=([], []))), \
             patch("integrations.webflow_sync.WebflowClient", return_value=mock_client), \
             patch("integrations.webflow_sync.sqlite3.connect", return_value=MagicMock()):

            asyncio.run(sync_pending_listings())

        # Creation MUST happen — without dedup safety, the only correct
        # behavior is to proceed and let DB-side INSERT OR IGNORE catch
        # duplicates on next run.
        mock_client.create_item_draft.assert_awaited_once()
