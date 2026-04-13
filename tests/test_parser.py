"""Tests for parser.py — field extraction from URLs and HTML."""
from integrations.parser import (
    parse_ad_type,
    parse_listing_id,
    parse_price_numeric,
    parse_property_type,
)


class TestParseListingId:
    def test_standard_url(self):
        url = "https://www.milanuncios.com/naves-industriales/nave-industrial-en-venta-123456789.htm"
        assert parse_listing_id(url) == "123456789"

    def test_shorter_id(self):
        url = "https://www.milanuncios.com/naves/nave-654321.htm"
        assert parse_listing_id(url) == "654321"

    def test_url_without_id_returns_none(self):
        assert parse_listing_id("https://www.milanuncios.com/naves/") is None

    def test_fallback_path_id(self):
        url = "https://www.milanuncios.com/detail/987654321"
        assert parse_listing_id(url) == "987654321"


class TestParsePriceNumeric:
    def test_from_json(self):
        ad = {"price": {"cashPrice": {"value": 350000}}}
        assert parse_price_numeric(ad) == 350000.0

    def test_none_when_no_json(self):
        assert parse_price_numeric(None) is None

    def test_none_when_no_price_key(self):
        assert parse_price_numeric({"price": {}}) is None


class TestParseAdType:
    def test_venta_from_url(self):
        assert parse_ad_type("https://milanuncios.com/venta-de-naves/x.htm") == "venta"

    def test_alquiler_from_url(self):
        assert parse_ad_type("https://milanuncios.com/alquiler-de-naves/x.htm") == "alquiler"

    def test_venta_from_json_sell_type(self):
        assert parse_ad_type("https://example.com", ad_json={"sellType": "supply"}) == "venta"

    def test_alquiler_from_json_category(self):
        ad = {"categories": [{"slug": "alquiler-naves", "name": "Alquiler naves"}]}
        assert parse_ad_type("https://example.com", ad_json=ad) == "alquiler"


class TestParsePropertyType:
    def test_from_url_naves(self):
        assert parse_property_type("https://milanuncios.com/naves-industriales/x.htm") == "Naves Industriales"

    def test_from_json_categories(self):
        ad = {"categories": [{"name": "Inmuebles"}, {"name": "Locales"}]}
        assert parse_property_type("https://example.com", ad_json=ad) == "Locales"
