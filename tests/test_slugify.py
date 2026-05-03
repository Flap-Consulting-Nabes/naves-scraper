"""Tests for slug generation — unicode handling, collisions, edge cases."""
from utils.slugify import (
    build_canonical_title,
    extract_warehouse_name,
    generate_unique_slug,
    slugify_title,
)


class TestSlugifyTitle:
    def test_basic_title(self):
        assert slugify_title("Nave Industrial en Venta", "1") == "nave-industrial-en-venta"

    def test_unicode_accents_removed(self):
        assert slugify_title("Polígono García López", "1") == "poligono-garcia-lopez"

    def test_special_chars_become_dashes(self):
        slug = slugify_title("Nave 1.200 m² (reformada)", "1")
        assert slug == "nave-1-200-m2-reformada"

    def test_empty_title_falls_back_to_listing_id(self):
        assert slugify_title("", "abc123") == "nave-abc123"
        assert slugify_title(None, "abc123") == "nave-abc123"

    def test_whitespace_only_falls_back(self):
        assert slugify_title("   ", "id1") == "nave-id1"

    def test_max_length_truncation(self):
        long_title = "a " * 100  # produces slug "a-a-a-a-..." much longer than 75
        slug = slugify_title(long_title, "1", max_length=20)
        assert len(slug) <= 20

    def test_no_trailing_dash_after_truncation(self):
        slug = slugify_title("word-" * 20, "1", max_length=10)
        assert not slug.endswith("-")

    def test_all_unicode_falls_back(self):
        # Title that becomes empty after transliteration
        assert slugify_title("日本語タイトル", "xyz") == "nave-xyz"


class TestGenerateUniqueSlug:
    def test_no_collision(self, mem_db):
        slug = generate_unique_slug(mem_db, "Nave en venta", "1")
        assert slug == "nave-en-venta"

    def test_first_collision_gets_suffix_2(self, mem_db):
        from db import insert_listing

        # Insert a listing that takes the base slug
        insert_listing(mem_db, {
            "listing_id": "first",
            "url": "https://example.com/1",
            "webflow_slug": "nave-en-venta",
        })
        slug = generate_unique_slug(mem_db, "Nave en venta", "second")
        assert slug == "nave-en-venta-2"

    def test_second_collision_gets_suffix_3(self, mem_db):
        from db import insert_listing

        insert_listing(mem_db, {
            "listing_id": "first",
            "url": "https://example.com/1",
            "webflow_slug": "nave-en-venta",
        })
        insert_listing(mem_db, {
            "listing_id": "second",
            "url": "https://example.com/2",
            "webflow_slug": "nave-en-venta-2",
        })
        slug = generate_unique_slug(mem_db, "Nave en venta", "third")
        assert slug == "nave-en-venta-3"

    def test_exclude_listing_id(self, mem_db):
        from db import insert_listing

        insert_listing(mem_db, {
            "listing_id": "self",
            "url": "https://example.com/1",
            "webflow_slug": "nave-en-venta",
        })
        # When excluding own row, base slug should be available
        slug = generate_unique_slug(mem_db, "Nave en venta", "self", exclude_listing_id="self")
        assert slug == "nave-en-venta"


# ─── Iteración 2026-05, Tarea 2: títulos canónicos ────────────────────────────
class TestExtractWarehouseName:
    def test_prefers_location_when_present(self):
        data = {
            "location": "Polígono Las Salinas (Cádiz)",
            "address": "Calle Mayor 5, 28045, Madrid",
        }
        assert extract_warehouse_name(data) == "Polígono Las Salinas (Cádiz)"

    def test_falls_back_to_address_when_no_location(self):
        data = {"location": "", "address": "Calle Mayor 5, 28045, Madrid, Madrid"}
        assert extract_warehouse_name(data) == "Calle Mayor 5"

    def test_falls_back_to_address_with_polígono(self):
        data = {"location": None, "address": "Polígono Industrial Norte, 41020, Sevilla"}
        assert extract_warehouse_name(data) == "Polígono Industrial Norte"

    def test_address_starting_with_cp_is_rejected(self):
        # "28045, Madrid, Madrid" — no street, just CP+city
        data = {"location": "", "address": "28045, Madrid, Madrid"}
        assert extract_warehouse_name(data) is None

    def test_address_without_street_keyword_is_rejected(self):
        # No `calle`/`avda`/`polígono` in the string
        data = {"location": "", "address": "Madrid, Madrid"}
        assert extract_warehouse_name(data) is None

    def test_both_empty_returns_none(self):
        assert extract_warehouse_name({"location": "", "address": ""}) is None

    def test_missing_keys_returns_none(self):
        assert extract_warehouse_name({}) is None


class TestBuildCanonicalTitle:
    def test_venta(self):
        assert build_canonical_title("venta", "Polígono Las Salinas") == \
            "Nave industrial en venta en Polígono Las Salinas"

    def test_alquiler(self):
        assert build_canonical_title("alquiler", "Madrid") == \
            "Nave industrial en alquiler en Madrid"

    def test_unknown_ad_type_returns_none(self):
        assert build_canonical_title("unknown", "Madrid") is None

    def test_missing_inputs_return_none(self):
        assert build_canonical_title(None, "Madrid") is None
        assert build_canonical_title("venta", None) is None
        assert build_canonical_title("venta", "") is None

