"""Tests for checkpoint_manager — load/save/reset with absolute paths."""
import json
import os
from pathlib import Path

from checkpoint_manager import (
    CHECKPOINT_FILE,
    load_checkpoint,
    reset_checkpoint,
    save_checkpoint,
)


class TestCheckpointPaths:
    def test_checkpoint_file_is_absolute(self):
        assert os.path.isabs(CHECKPOINT_FILE), "CHECKPOINT_FILE must be an absolute path"

    def test_checkpoint_file_points_to_project_root(self):
        path = Path(CHECKPOINT_FILE)
        # Should be in the same directory as checkpoint_manager.py
        assert path.parent == Path(__file__).parent.parent


class TestCheckpointLifecycle:
    def setup_method(self):
        """Remove checkpoint file before each test."""
        if os.path.exists(CHECKPOINT_FILE):
            os.remove(CHECKPOINT_FILE)

    def teardown_method(self):
        """Clean up after tests."""
        if os.path.exists(CHECKPOINT_FILE):
            os.remove(CHECKPOINT_FILE)

    def test_load_returns_defaults_when_no_file(self):
        cp = load_checkpoint()
        assert cp == {"last_page": 1, "last_listing_id": None}

    def test_save_and_load_roundtrip(self):
        save_checkpoint(5, "abc-123")
        cp = load_checkpoint()
        assert cp["last_page"] == 5
        assert cp["last_listing_id"] == "abc-123"

    def test_reset_removes_file(self):
        save_checkpoint(3, "xyz")
        assert os.path.exists(CHECKPOINT_FILE)
        reset_checkpoint()
        assert not os.path.exists(CHECKPOINT_FILE)

    def test_load_after_reset_returns_defaults(self):
        save_checkpoint(10, "test")
        reset_checkpoint()
        cp = load_checkpoint()
        assert cp["last_page"] == 1

    def test_load_handles_corrupt_file(self):
        with open(CHECKPOINT_FILE, "w") as f:
            f.write("not valid json{{{")
        cp = load_checkpoint()
        assert cp == {"last_page": 1, "last_listing_id": None}

    def test_negative_page_clamped_to_one(self):
        with open(CHECKPOINT_FILE, "w") as f:
            json.dump({"last_page": -5, "last_listing_id": None}, f)
        cp = load_checkpoint()
        assert cp["last_page"] == 1
