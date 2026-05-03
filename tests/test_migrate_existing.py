"""Tests for scripts/migrate_existing_listings.recompute_row.

Iteración 2026-05 (Bloque G1): the migration must propose only the fields
that actually changed for a given row, and skip rows where nothing needs
updating.
"""
from scripts.migrate_existing_listings import recompute_row


class TestRecomputeRow:
    def test_noop_when_already_canonical_and_complete(self):
        row = {
            "listing_id": "1",
            "url": "https://milanuncios.com/venta-de-naves/x.htm",
            "ad_type": "venta",
            "title": "Nave industrial en venta en Madrid",
            "original_title": "old",
            "webflow_slug": "nave-industrial-en-venta-en-madrid",
            "location": "Madrid",
            "address": "",
            "latitude": 40.4,
            "longitude": -3.7,
            "description": "<p>Already HTML.</p>",
            "raw_html": None,
        }
        assert recompute_row(row) == {}

    def test_proposes_canonical_title_when_raw(self):
        row = {
            "listing_id": "2",
            "url": "https://milanuncios.com/alquiler-de-naves/y.htm",
            "ad_type": "alquiler",
            "title": "Alquiler de nave",  # not canonical
            "original_title": None,
            "webflow_slug": "alquiler-de-nave",
            "location": "Barcelona",
            "address": "",
            "latitude": 41.4,
            "longitude": 2.1,
            "description": "<p>x</p>",
            "raw_html": None,
        }
        out = recompute_row(row)
        assert out["title"] == "Nave industrial en alquiler en Barcelona"
        assert out["original_title"] == "Alquiler de nave"

    def test_proposes_html_for_plaintext_description(self):
        row = {
            "listing_id": "3",
            "url": "https://example.com",
            "ad_type": "venta",
            "title": "Nave industrial en venta en Madrid",
            "original_title": "x",
            "webflow_slug": "s",
            "location": "Madrid",
            "address": "",
            "latitude": 1.0,
            "longitude": 1.0,
            "description": "Linea uno.\n\nLinea dos.",
            "raw_html": None,
        }
        out = recompute_row(row)
        assert out["description"] == "<p>Linea uno.</p><p>Linea dos.</p>"

    def test_does_not_double_wrap_html_description(self):
        row = {
            "listing_id": "4",
            "url": "https://example.com",
            "ad_type": "venta",
            "title": "Nave industrial en venta en Madrid",
            "original_title": "x",
            "webflow_slug": "s",
            "location": "Madrid",
            "address": "",
            "latitude": 1.0,
            "longitude": 1.0,
            "description": "<p>Already wrapped</p>",
            "raw_html": None,
        }
        out = recompute_row(row)
        assert "description" not in out

    def test_skips_canonical_when_no_name_available(self):
        row = {
            "listing_id": "5",
            "url": "https://example.com",
            "ad_type": "venta",
            "title": "Nave",
            "original_title": None,
            "webflow_slug": "nave",
            "location": "",   # nothing usable
            "address": "",
            "latitude": 1.0,
            "longitude": 1.0,
            "description": "<p>x</p>",
            "raw_html": None,
        }
        out = recompute_row(row)
        # No title proposed because there's no Name → nothing changes
        assert "title" not in out
