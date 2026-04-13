"""Tests for the centralized logging configuration."""
import logging
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from utils.logging_config import (
    ERROR_KEYWORDS,
    get_error_log_handler,
    get_scraper_log_handler,
    is_error_line,
    reset_logging,
    setup_logging,
)


@pytest.fixture(autouse=True)
def _clean_logging(tmp_path):
    """Reset logging state before and after each test."""
    reset_logging()
    yield
    reset_logging()


@pytest.fixture()
def log_dir(tmp_path):
    """Patch LOG_DIR to use a temp directory for file handler tests."""
    with (
        patch("utils.logging_config.LOG_DIR", tmp_path),
        patch("utils.logging_config.ERROR_LOG", tmp_path / "errors.log"),
        patch("utils.logging_config.SCRAPER_LOG", tmp_path / "scraper.log"),
        patch("utils.logging_config.API_ERROR_LOG", tmp_path / "api_errors.log"),
    ):
        yield tmp_path


# ── setup_logging ────────────────────────────────────────────────────────────


class TestSetupLogging:
    def test_adds_console_handler(self, log_dir):
        setup_logging()
        root = logging.getLogger()
        stream_handlers = [
            h for h in root.handlers
            if type(h) is logging.StreamHandler
        ]
        assert len(stream_handlers) == 1

    def test_adds_error_file_handler(self, log_dir):
        setup_logging()
        root = logging.getLogger()
        file_handlers = [h for h in root.handlers if hasattr(h, "baseFilename")]
        error_handlers = [h for h in file_handlers if h.level == logging.ERROR]
        assert len(error_handlers) == 1
        assert "errors.log" in error_handlers[0].baseFilename

    def test_api_mode_uses_api_error_log(self, log_dir):
        setup_logging(api_mode=True)
        root = logging.getLogger()
        file_handlers = [h for h in root.handlers if hasattr(h, "baseFilename")]
        error_handlers = [h for h in file_handlers if h.level == logging.ERROR]
        assert len(error_handlers) == 1
        assert "api_errors.log" in error_handlers[0].baseFilename

    def test_include_file_log_adds_scraper_log(self, log_dir):
        setup_logging(include_file_log=True)
        root = logging.getLogger()
        file_handlers = [h for h in root.handlers if hasattr(h, "baseFilename")]
        info_handlers = [h for h in file_handlers if h.level == logging.INFO]
        assert len(info_handlers) == 1
        assert "scraper.log" in info_handlers[0].baseFilename

    def test_idempotent(self, log_dir):
        setup_logging()
        count = len(logging.getLogger().handlers)
        setup_logging()
        assert len(logging.getLogger().handlers) == count

    def test_error_written_to_file(self, log_dir):
        setup_logging()
        test_logger = logging.getLogger("test_error_write")
        test_logger.error("Test error message for persistence")
        # Flush handlers
        for h in logging.getLogger().handlers:
            h.flush()
        error_log = log_dir / "errors.log"
        assert error_log.exists()
        content = error_log.read_text()
        assert "Test error message for persistence" in content

    def test_info_not_in_error_log(self, log_dir):
        setup_logging()
        test_logger = logging.getLogger("test_info_skip")
        test_logger.info("This is just info")
        for h in logging.getLogger().handlers:
            h.flush()
        error_log = log_dir / "errors.log"
        if error_log.exists():
            assert "This is just info" not in error_log.read_text()


# ── is_error_line ────────────────────────────────────────────────────────────


class TestIsErrorLine:
    @pytest.mark.parametrize("line", [
        "2025-04-13 10:00:00 [ERROR] scraper — Connection refused",
        "Traceback (most recent call last):",
        "RuntimeError: coroutine raised StopIteration",
        "ScrapeBanException: Kasada header detected",
        "SessionExpiredException: redirect to login",
        "Fatal unhandled exception — scraper crashed",
        "ConnectionError: failed to reach host",
    ])
    def test_detects_error_lines(self, line):
        assert is_error_line(line) is True

    @pytest.mark.parametrize("line", [
        "2025-04-13 10:00:00 [INFO] scraper — Page 1 loaded",
        "Nuevos insertados: 15",
        "Warm-up completo en 3.2s",
        "[CAPTCHA_SOLVED]",
        "Duplicados saltados: 5",
    ])
    def test_ignores_normal_lines(self, line):
        assert is_error_line(line) is False

    def test_case_insensitive(self):
        assert is_error_line("TRACEBACK (MOST RECENT CALL LAST):") is True


# ── Subprocess log handlers ──────────────────────────────────────────────────


class TestSubprocessHandlers:
    def test_scraper_log_handler_creates_file(self, log_dir):
        handler = get_scraper_log_handler()
        record = logging.LogRecord(
            name="test", level=logging.INFO,
            pathname="", lineno=0, msg="test line",
            args=(), exc_info=None,
        )
        handler.emit(record)
        handler.close()
        assert (log_dir / "scraper.log").exists()

    def test_error_log_handler_creates_file(self, log_dir):
        handler = get_error_log_handler()
        record = logging.LogRecord(
            name="test", level=logging.ERROR,
            pathname="", lineno=0, msg="critical failure",
            args=(), exc_info=None,
        )
        handler.emit(record)
        handler.close()
        log_content = (log_dir / "errors.log").read_text()
        assert "critical failure" in log_content
        assert "[SCRAPER-ERROR]" in log_content


# ── reset_logging ────────────────────────────────────────────────────────────


class TestResetLogging:
    def test_removes_all_handlers(self, log_dir):
        setup_logging()
        assert len(logging.getLogger().handlers) > 0
        reset_logging()
        assert len(logging.getLogger().handlers) == 0

    def test_allows_reconfiguration(self, log_dir):
        setup_logging()
        reset_logging()
        setup_logging(api_mode=True)
        file_handlers = [
            h for h in logging.getLogger().handlers
            if hasattr(h, "baseFilename")
        ]
        error_handlers = [h for h in file_handlers if h.level == logging.ERROR]
        assert "api_errors.log" in error_handlers[0].baseFilename
