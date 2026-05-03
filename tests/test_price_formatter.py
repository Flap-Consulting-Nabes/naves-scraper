"""Tests for utils.price_formatter (Iteración 2026-05, Tarea 5)."""
import pytest

from utils.price_formatter import format_price_display


class TestVenta:
    def test_basic_thousands_separator(self):
        assert format_price_display("venta", 199000, None) == "199.000 €"

    def test_high_price_with_full_separators(self):
        assert format_price_display("venta", 1_250_000, None) == "1.250.000 €"

    def test_decimal_rounded_not_truncated(self):
        # 199500.6 must round UP to 199501; int() would truncate to 199500
        assert format_price_display("venta", 199500.6, None) == "199.501 €"

    def test_decimal_rounded_down(self):
        assert format_price_display("venta", 199500.4, None) == "199.500 €"

    def test_returns_none_when_price_missing(self):
        assert format_price_display("venta", None, None) is None


class TestAlquiler:
    def test_per_m2_two_decimals(self):
        assert format_price_display("alquiler", None, 1.19) == "1.19€/m²"

    def test_per_m2_rounds_to_two_decimals(self):
        assert format_price_display("alquiler", None, 1.196) == "1.20€/m²"

    def test_per_m2_pads_zero(self):
        assert format_price_display("alquiler", None, 5.0) == "5.00€/m²"

    def test_falls_back_to_monthly_total_when_no_per_m2(self):
        assert format_price_display("alquiler", 1500, None) == "1.500 €/mes"

    def test_per_m2_takes_precedence_over_monthly(self):
        assert format_price_display("alquiler", 1500, 1.19) == "1.19€/m²"

    def test_returns_none_when_both_missing(self):
        assert format_price_display("alquiler", None, None) is None


class TestUnknownType:
    @pytest.mark.parametrize("ad_type", [None, "", "unknown", "transfer"])
    def test_unknown_type_returns_none(self, ad_type):
        assert format_price_display(ad_type, 199000, 1.19) is None
