"""Tests for parser.py — field extraction from URLs and HTML."""
from integrations.parser import (
    parse_ad_type,
    parse_coordinates,
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

    def test_undetectable_returns_none_and_logs_warning(self, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger="integrations.parser"):
            result = parse_ad_type("https://example.com/some/path", ad_json=None)
        assert result is None
        assert any("ad_type undetectable" in rec.message for rec in caplog.records)

    # ── Iteración 2026-05-04: capa 4 keyword scan ─────────────────────
    def test_body_keyword_alquiler_when_url_neutral(self):
        result = parse_ad_type(
            "https://example.com/x.htm",
            description="Se alquila nave industrial. Renta de 1500 euros mensuales.",
        )
        assert result == "alquiler"

    def test_body_keyword_venta_when_url_neutral(self):
        result = parse_ad_type(
            "https://example.com/x.htm",
            description="Se vende nave de 1.200 m². Compraventa rápida.",
        )
        assert result == "venta"

    def test_per_m2_pattern_signals_alquiler(self):
        result = parse_ad_type(
            "https://example.com/x.htm",
            description="Excelente nave a 1.19€/m².",
        )
        assert result == "alquiler"

    def test_url_overridden_by_strong_body_signal(self, caplog):
        # URL says venta, body strongly says alquiler — body wins.
        import logging
        with caplog.at_level(logging.WARNING, logger="integrations.parser"):
            result = parse_ad_type(
                "https://milanuncios.com/venta-de-naves/x.htm",
                title="Se alquila nave",
                description="Se alquila por 2.500 €/mes. Renta mensual.",
            )
        assert result == "alquiler"
        assert any("URL says venta but body votes alquiler" in r.message for r in caplog.records)

    def test_url_kept_when_body_weak(self):
        # URL says venta, body has only one alquiler hit — keep URL.
        result = parse_ad_type(
            "https://milanuncios.com/venta-de-naves/x.htm",
            description="Posibilidad de alquiler también.",
        )
        assert result == "venta"

    def test_demand_in_json_means_alquiler(self):
        result = parse_ad_type(
            "https://example.com/x.htm",
            ad_json={"sellType": "demand"},
        )
        assert result == "alquiler"

    def test_traspaso_keyword_counts_as_venta(self):
        result = parse_ad_type(
            "https://example.com/x.htm",
            description="Se traspasa local industrial bien situado.",
        )
        assert result == "venta"

    def test_tied_body_returns_none(self, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger="integrations.parser"):
            result = parse_ad_type(
                "https://example.com/x.htm",
                description="Venta o alquiler, ambas opciones.",
            )
        assert result is None
        assert any("ad_type tied in body" in r.message for r in caplog.records)

    # ── Dual offering detection (venta_alquiler) ──────────────────────
    def test_dual_offering_when_both_keyword_families_strong(self):
        # >= 2 hits of each family → dual offering, even with no URL hint.
        result = parse_ad_type(
            "https://example.com/x.htm",
            description=(
                "Se vende o alquila nave industrial. Consulte precio de "
                "VENTA o ALQUILER. Posibilidad de venta directa o renta "
                "mensual con arriendo flexible."
            ),
        )
        assert result == "venta_alquiler"

    def test_dual_offering_overrides_url_alquiler_hint(self):
        # Real-world scenario: listing published under /alquiler-de-naves/
        # but the ad explicitly offers both modalities. URL hint loses.
        result = parse_ad_type(
            "https://milanuncios.com/alquiler-de-naves/don-benito.htm",
            title="Nave 902 m² céntrica",
            description=(
                "Ofrecemos esta propiedad bajo una doble modalidad "
                "(venta o alquiler). Consulte precio de VENTA o ALQUILER. "
                "Disponible para venta directa o arriendo mensual."
            ),
        )
        assert result == "venta_alquiler"

    def test_dual_offering_overrides_url_venta_hint(self):
        result = parse_ad_type(
            "https://milanuncios.com/venta-de-naves/x.htm",
            description=(
                "Vendo o alquilo nave. Compraventa o arriendo. Renta "
                "mensual disponible. Venta directa también."
            ),
        )
        assert result == "venta_alquiler"

    def test_single_phrase_does_not_trigger_dual(self):
        # A single mention of each family → tie / single, not dual.
        result = parse_ad_type(
            "https://example.com/x.htm",
            description="Se vende. Posibilidad de alquiler.",
        )
        # 1 venta hit + 1 alquiler hit → tied → None (existing behavior preserved)
        assert result is None


class TestParsePropertyType:
    def test_from_url_naves(self):
        assert parse_property_type("https://milanuncios.com/naves-industriales/x.htm") == "Naves Industriales"

    def test_from_json_categories(self):
        ad = {"categories": [{"name": "Inmuebles"}, {"name": "Locales"}]}
        assert parse_property_type("https://example.com", ad_json=ad) == "Locales"


class TestParseCoordinates:
    """Iteración 2026-05: lat/lng must be extracted from ad_json.location.geolocation."""

    def test_returns_none_when_no_json(self):
        assert parse_coordinates(None) == (None, None)

    def test_returns_none_when_no_geolocation(self):
        assert parse_coordinates({"location": {}}) == (None, None)

    def test_returns_floats_from_geolocation(self):
        ad = {"location": {"geolocation": {"latitude": 40.4168, "longitude": -3.7038}}}
        lat, lng = parse_coordinates(ad)
        assert lat == 40.4168
        assert lng == -3.7038

    def test_partial_geolocation_returns_none_for_missing(self):
        ad = {"location": {"geolocation": {"latitude": 40.4168}}}
        lat, lng = parse_coordinates(ad)
        assert lat == 40.4168
        assert lng is None
