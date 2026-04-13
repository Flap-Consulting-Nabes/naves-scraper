"""Tests for database layer: schema, migration, CRUD, pagination."""
import re

from db import (
    _ALLOWED_TYPES,
    _NEW_COLUMNS,
    _VALID_COL_RE,
    _safe_add_column,
    count_listings,
    get_listings_paginated,
    insert_listing,
    listing_exists,
)


class TestSchemaMigration:
    def test_init_creates_listings_table(self, mem_db):
        tables = mem_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='listings'"
        ).fetchall()
        assert len(tables) == 1

    def test_new_columns_exist_after_init(self, mem_db):
        cols = {row[1] for row in mem_db.execute("PRAGMA table_info(listings)")}
        for col, _ in _NEW_COLUMNS:
            assert col in cols, f"Missing column: {col}"

    def test_safe_add_column_rejects_invalid_name(self, mem_db):
        import pytest

        with pytest.raises(ValueError, match="Invalid column name"):
            _safe_add_column(mem_db, "DROP TABLE--", "TEXT")

    def test_safe_add_column_rejects_invalid_type(self, mem_db):
        import pytest

        with pytest.raises(ValueError, match="Invalid column type"):
            _safe_add_column(mem_db, "good_col", "DROP TABLE")

    def test_valid_col_regex_accepts_good_names(self):
        for name in ["title", "price_numeric", "webflow_item_id", "a1"]:
            assert _VALID_COL_RE.match(name), f"Should accept: {name}"

    def test_valid_col_regex_rejects_bad_names(self):
        for name in ["DROP TABLE", "123abc", "a" * 64, "", "col;--"]:
            assert not _VALID_COL_RE.match(name), f"Should reject: {name}"

    def test_allowed_types(self):
        assert "TEXT" in _ALLOWED_TYPES
        assert "REAL" in _ALLOWED_TYPES
        assert "INTEGER" in _ALLOWED_TYPES
        assert "TIMESTAMP" in _ALLOWED_TYPES


class TestInsertAndDedup:
    def test_insert_listing_returns_true(self, mem_db, sample_listing):
        assert insert_listing(mem_db, sample_listing) is True

    def test_duplicate_insert_returns_false(self, mem_db, sample_listing):
        insert_listing(mem_db, sample_listing)
        assert insert_listing(mem_db, sample_listing) is False

    def test_listing_exists_after_insert(self, mem_db, sample_listing):
        assert listing_exists(mem_db, "123456789") is False
        insert_listing(mem_db, sample_listing)
        assert listing_exists(mem_db, "123456789") is True

    def test_count_listings(self, mem_db, sample_listing):
        assert count_listings(mem_db) == 0
        insert_listing(mem_db, sample_listing)
        assert count_listings(mem_db) == 1


class TestPagination:
    def _insert_n(self, mem_db, sample_listing, n):
        for i in range(n):
            data = {**sample_listing, "listing_id": f"id-{i}", "url": f"https://example.com/{i}"}
            insert_listing(mem_db, data)

    def test_pagination_returns_correct_page(self, mem_db, sample_listing):
        self._insert_n(mem_db, sample_listing, 5)
        rows, total = get_listings_paginated(mem_db, page=1, page_size=3)
        assert total == 5
        assert len(rows) == 3

    def test_pagination_page_two(self, mem_db, sample_listing):
        self._insert_n(mem_db, sample_listing, 5)
        rows, total = get_listings_paginated(mem_db, page=2, page_size=3)
        assert total == 5
        assert len(rows) == 2

    def test_filter_by_province(self, mem_db, sample_listing):
        insert_listing(mem_db, {**sample_listing, "listing_id": "a1", "province": "Valencia"})
        insert_listing(mem_db, {**sample_listing, "listing_id": "a2", "province": "Madrid"})
        rows, total = get_listings_paginated(mem_db, province="Valencia")
        assert total == 1
        assert rows[0]["province"] == "Valencia"

    def test_filter_by_min_surface(self, mem_db, sample_listing):
        insert_listing(mem_db, {**sample_listing, "listing_id": "s1", "surface_m2": 500.0})
        insert_listing(mem_db, {**sample_listing, "listing_id": "s2", "surface_m2": 2000.0})
        rows, total = get_listings_paginated(mem_db, min_surface=1000.0)
        assert total == 1
        assert rows[0]["surface_m2"] == 2000.0

    def test_filter_by_max_price(self, mem_db, sample_listing):
        insert_listing(mem_db, {**sample_listing, "listing_id": "p1", "price_numeric": 100000.0})
        insert_listing(mem_db, {**sample_listing, "listing_id": "p2", "price_numeric": 500000.0})
        rows, total = get_listings_paginated(mem_db, max_price=200000.0)
        assert total == 1
        assert rows[0]["price_numeric"] == 100000.0

    def test_sort_rejects_invalid_column(self, mem_db, sample_listing):
        """Invalid sort_by should fall back to scraped_at."""
        insert_listing(mem_db, sample_listing)
        rows, total = get_listings_paginated(mem_db, sort_by="DROP TABLE listings")
        assert total == 1  # query still works, didn't inject
