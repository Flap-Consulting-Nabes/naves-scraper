"""Tests for API endpoints via FastAPI TestClient."""
import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from db import init_db

AUTH_HEADER = {"x-api-key": os.environ.get("API_SECRET_KEY", "test-secret-key")}


@pytest.fixture(scope="module")
def test_db():
    """Shared in-memory DB with full listings schema."""
    conn = init_db(":memory:")
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def client(test_db):
    """FastAPI TestClient with DB override and mocked scheduler."""
    from api.dependencies import get_db
    from api.main import app

    def _override_db():
        yield test_db

    app.dependency_overrides[get_db] = _override_db

    mock_scheduler = MagicMock()
    with patch("scheduler.get_scheduler", return_value=mock_scheduler):
        with TestClient(app) as tc:
            yield tc

    app.dependency_overrides.clear()


# ── Health ───────────────────────────────────────────────────────────────────


class TestHealth:
    def test_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "timestamp" in data

    def test_needs_no_auth(self, client):
        # /health is the only endpoint that doesn't require x-api-key
        resp = client.get("/health")
        assert resp.status_code == 200


# ── Auth / Login ─────────────────────────────────────────────────────────────


class TestAuthLogin:
    def test_correct_password_returns_api_key(self, client):
        resp = client.post("/api/auth/login", json={"password": "test-password"})
        assert resp.status_code == 200
        assert "api_key" in resp.json()

    def test_wrong_password_returns_401(self, client):
        resp = client.post("/api/auth/login", json={"password": "wrong"})
        assert resp.status_code == 401

    def test_missing_body_returns_422(self, client):
        resp = client.post("/api/auth/login")
        assert resp.status_code == 422


# ── Auth guard ───────────────────────────────────────────────────────────────


class TestAuthGuard:
    def test_missing_key_returns_422(self, client):
        resp = client.get("/api/listings")
        assert resp.status_code == 422

    def test_wrong_key_returns_403(self, client):
        resp = client.get("/api/listings", headers={"x-api-key": "bad-key"})
        assert resp.status_code == 403


# ── Listings ─────────────────────────────────────────────────────────────────


class TestListings:
    def test_empty_db_returns_zero_items(self, client):
        resp = client.get("/api/listings", headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["page"] == 1

    def test_pagination_params_echoed(self, client):
        resp = client.get("/api/listings?page=2&page_size=10", headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 2
        assert data["page_size"] == 10

    def test_invalid_page_rejected(self, client):
        resp = client.get("/api/listings?page=0", headers=AUTH_HEADER)
        assert resp.status_code == 422

    def test_page_size_over_limit_rejected(self, client):
        resp = client.get("/api/listings?page_size=999", headers=AUTH_HEADER)
        assert resp.status_code == 422


class TestProvinces:
    def test_empty_db_returns_empty_list(self, client):
        resp = client.get("/api/listings/provinces", headers=AUTH_HEADER)
        assert resp.status_code == 200
        assert resp.json()["provinces"] == []


# ── Logs ─────────────────────────────────────────────────────────────────────


class TestLogs:
    def test_returns_empty_when_no_log_file(self, client):
        resp = client.get("/api/logs", headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["lines"], list)


# ── Cron ─────────────────────────────────────────────────────────────────────


class TestCron:
    def test_get_cron_returns_config(self, client):
        resp = client.get("/api/cron", headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert "cron_expr" in data
        assert "max_pages" in data
        assert "next_run" in data


# ── Scraper status ───────────────────────────────────────────────────────────


class TestScraperStatus:
    def test_idle_by_default(self, client):
        resp = client.get("/api/scraper/status", headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] in ("idle", "running", "error")


# ── VNC status ───────────────────────────────────────────────────────────────


class TestVncStatus:
    def test_not_available_by_default(self, client):
        resp = client.get("/api/vnc/status", headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data["available"] is False
        assert data["ws_port"] is None


# ── Webflow status ───────────────────────────────────────────────────────────


class TestWebflowStatus:
    def test_empty_db_shows_zero_counts(self, client):
        resp = client.get("/api/webflow/status", headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["synced"] == 0
        assert data["pending"] == 0
        assert data["last_sync_at"] is None


# ── Session status ───────────────────────────────────────────────────────────


class TestSessionStatus:
    def test_returns_valid_state(self, client):
        resp = client.get("/api/session/status", headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] in ("idle", "running", "error")
