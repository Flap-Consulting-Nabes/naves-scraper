"""Shared fixtures for the test suite."""
import os
import sqlite3

import pytest

# Ensure tests never touch production DB or services
os.environ.setdefault("DB_PATH", ":memory:")
os.environ.setdefault("API_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "test-password")
os.environ.setdefault("WEBFLOW_TOKEN", "")
os.environ.setdefault("WEBFLOW_COLLECTION_ID", "")


@pytest.fixture()
def mem_db():
    """In-memory SQLite database with the full listings schema applied."""
    from db import init_db

    conn = init_db(":memory:")
    yield conn
    conn.close()


@pytest.fixture()
def sample_listing():
    """Minimal valid listing dict for insert_listing()."""
    return {
        "listing_id": "123456789",
        "url": "https://www.milanuncios.com/naves-industriales/nave-en-venta-123456789.htm",
        "title": "Nave industrial en polígono Fuente del Jarro",
        "description": "Gran nave industrial con oficinas",
        "price": "350.000 €",
        "price_numeric": 350000.0,
        "price_per_m2": 291.67,
        "surface_m2": 1200.0,
        "rooms": None,
        "bathrooms": 2,
        "floor": None,
        "condition": "segunda mano",
        "energy_certificate": "E",
        "features": ["Altillo", "Puente grúa"],
        "ad_type": "venta",
        "property_type": "Naves Industriales",
        "location": "Paterna (Valencia)",
        "province": "Valencia",
        "address": "Polígono Fuente del Jarro",
        "zipcode": "46988",
        "seller_type": "profesional",
        "seller_name": "Inmobiliaria Test",
        "seller_id": "u-abc123",
        "seller_url": "https://www.milanuncios.com/profesionales/inmobiliaria-test/",
        "phone": "600123456",
        "phone2": None,
        "photos": ["https://example.com/img1.jpg", "https://example.com/img2.jpg"],
        "published_at": "2025-01-15T10:00:00",
        "updated_at": "2025-02-20T14:30:00",
        "raw_html": "<html>test</html>",
        "reference": "REF-001",
        "webflow_slug": None,
    }
