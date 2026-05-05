"""Price display formatter for Webflow CMS.

Iteración 2026-05 (Tarea 5):
- Venta:    "199.000 €"   (formato ES, separador de miles con punto)
- Alquiler: "1.19€/m²"    (decimal con punto, dos decimales)
- Alquiler sin price_per_m2: fallback "1.500 €/mes" usando price_numeric

The single source of truth for the display string lives here so both the
scraper sync path (`integrations.webflow_sync`) and the migration script
(`scripts/migrate_existing_listings.py`) produce identical output.
"""
from __future__ import annotations


def format_price_display(
    ad_type: str | None,
    price_numeric: float | None,
    price_per_m2: float | None,
) -> str | None:
    """Build the display string Webflow's price field expects.

    Returns None when neither input is usable so callers can decide
    whether to fall back to the parser's raw `price` string or leave the
    field empty.
    """
    if ad_type == "venta" and price_numeric is not None:
        return _format_thousands_es(price_numeric) + " €"

    # Dual offerings ("venta_alquiler") inherit the alquiler routing: the
    # MilAnuncios price field for these listings is the rental rate (per-m²
    # or monthly), so we format it the same way. The sale slot stays empty
    # because the listing rarely quotes both prices.
    if ad_type in ("alquiler", "venta_alquiler"):
        if price_per_m2 is not None:
            return f"{price_per_m2:.2f}€/m²"
        if price_numeric is not None:
            return _format_thousands_es(price_numeric) + " €/mes"

    return None


def _format_thousands_es(value: float) -> str:
    """Format an integer-rounded value with `.` as thousands separator (ES locale).

    `round()` instead of `int()` so prices like 199500.5 don't truncate to 199500.
    Negative numbers are formatted with the minus sign in front of the digits.
    """
    return f"{round(value):,}".replace(",", ".")
