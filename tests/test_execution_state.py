#!/usr/bin/env python3
"""Unit tests for execution_state.py checkpoint management."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

# Load the module under test
_MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "execution_state.py"
_spec = importlib.util.spec_from_file_location("execution_state", _MODULE_PATH)
assert _spec and _spec.loader
_execution_state = importlib.util.module_from_spec(_spec)
sys.modules["execution_state"] = _execution_state
_spec.loader.exec_module(_execution_state)  # type: ignore[union-attr]


class TestSaveCheckpoint:
    """Tests for save_checkpoint function."""

    def test_creates_checkpoint_file(self, tmp_path: Path) -> None:
        """Verify checkpoint file is created with correct content."""
        state_file = tmp_path / "logs" / ".execution-state.json"

        with patch.object(_execution_state, "STATE_FILE", state_file):
            _execution_state.save_checkpoint(
                branch="agent/test-feature",
                plan_file="PLAN-test-feature.md",
                current_step=3,
                total_steps=10,
            )

        assert state_file.exists()
        content = json.loads(state_file.read_text(encoding="utf-8"))
        assert content["branch"] == "agent/test-feature"
        assert content["plan_file"] == "PLAN-test-feature.md"
        assert content["current_step"] == 3
        assert content["total_steps"] == 10
        assert content["status"] == "IN_PROGRESS"
        assert "last_updated" in content

    def test_overwrites_existing_checkpoint(self, tmp_path: Path) -> None:
        """Verify save overwrites previous checkpoint."""
        state_file = tmp_path / "logs" / ".execution-state.json"
        state_file.parent.mkdir(parents=True)
        state_file.write_text('{"old": "data"}', encoding="utf-8")

        with patch.object(_execution_state, "STATE_FILE", state_file):
            _execution_state.save_checkpoint(
                branch="agent/new",
                plan_file="PLAN-new.md",
                current_step=1,
                total_steps=5,
            )

        content = json.loads(state_file.read_text(encoding="utf-8"))
        assert content["branch"] == "agent/new"
        assert "old" not in content


class TestLoadCheckpoint:
    """Tests for load_checkpoint function."""

    def test_returns_none_when_no_file(self, tmp_path: Path) -> None:
        """Verify None returned when checkpoint doesn't exist."""
        state_file = tmp_path / "logs" / ".execution-state.json"

        with patch.object(_execution_state, "STATE_FILE", state_file):
            result = _execution_state.load_checkpoint()

        assert result is None

    def test_loads_valid_checkpoint(self, tmp_path: Path) -> None:
        """Verify valid checkpoint is loaded correctly."""
        state_file = tmp_path / "logs" / ".execution-state.json"
        state_file.parent.mkdir(parents=True)
        state_file.write_text(
            json.dumps(
                {
                    "branch": "agent/test",
                    "plan_file": "PLAN-test.md",
                    "current_step": 5,
                    "total_steps": 10,
                    "status": "IN_PROGRESS",
                    "last_updated": "2026-03-29T10:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )

        with patch.object(_execution_state, "STATE_FILE", state_file):
            result = _execution_state.load_checkpoint()

        assert result is not None
        assert result["branch"] == "agent/test"
        assert result["current_step"] == 5

    def test_returns_none_for_malformed_json(self, tmp_path: Path) -> None:
        """Verify None returned for invalid JSON."""
        state_file = tmp_path / "logs" / ".execution-state.json"
        state_file.parent.mkdir(parents=True)
        state_file.write_text("not valid json", encoding="utf-8")

        with patch.object(_execution_state, "STATE_FILE", state_file):
            result = _execution_state.load_checkpoint()

        assert result is None

    def test_returns_none_for_missing_fields(self, tmp_path: Path) -> None:
        """Verify None returned when required fields are missing."""
        state_file = tmp_path / "logs" / ".execution-state.json"
        state_file.parent.mkdir(parents=True)
        state_file.write_text('{"branch": "test"}', encoding="utf-8")  # Missing other fields

        with patch.object(_execution_state, "STATE_FILE", state_file):
            result = _execution_state.load_checkpoint()

        assert result is None


class TestClearCheckpoint:
    """Tests for clear_checkpoint function."""

    def test_deletes_existing_checkpoint(self, tmp_path: Path) -> None:
        """Verify checkpoint file is deleted."""
        state_file = tmp_path / "logs" / ".execution-state.json"
        state_file.parent.mkdir(parents=True)
        state_file.write_text("{}", encoding="utf-8")

        with patch.object(_execution_state, "STATE_FILE", state_file):
            with patch("subprocess.run") as mock_run:
                result = _execution_state.clear_checkpoint()

        assert result is True
        assert not state_file.exists()
        mock_run.assert_called_once()

    def test_returns_false_when_no_checkpoint(self, tmp_path: Path) -> None:
        """Verify False returned when no checkpoint exists."""
        state_file = tmp_path / "logs" / ".execution-state.json"

        with patch.object(_execution_state, "STATE_FILE", state_file):
            with patch("subprocess.run") as mock_run:
                result = _execution_state.clear_checkpoint()

        assert result is False
        mock_run.assert_not_called()


class TestGetCheckpointAgeMinutes:
    """Tests for get_checkpoint_age_minutes function."""

    def test_returns_none_when_no_checkpoint(self, tmp_path: Path) -> None:
        """Verify None returned when checkpoint doesn't exist."""
        state_file = tmp_path / "logs" / ".execution-state.json"

        with patch.object(_execution_state, "STATE_FILE", state_file):
            result = _execution_state.get_checkpoint_age_minutes()

        assert result is None

    def test_returns_age_for_valid_checkpoint(self, tmp_path: Path) -> None:
        """Verify age is calculated correctly."""
        state_file = tmp_path / "logs" / ".execution-state.json"
        state_file.parent.mkdir(parents=True)

        # Create checkpoint with known timestamp
        with patch.object(_execution_state, "STATE_FILE", state_file):
            _execution_state.save_checkpoint(
                branch="agent/test",
                plan_file="PLAN-test.md",
                current_step=1,
                total_steps=5,
            )
            age = _execution_state.get_checkpoint_age_minutes()

        assert age is not None
        assert age >= 0  # Should be very small (just created)
        assert age < 1  # Less than 1 minute old


class TestTodoStatePersistence:
    """Tests for todo_state parameter in save/load checkpoint."""

    def test_save_and_load_with_todo_state(self, tmp_path: Path) -> None:
        """Verify todo_state is saved and loaded correctly."""
        state_file = tmp_path / "logs" / ".execution-state.json"
        todos = [
            {"id": 1, "title": "Step 1", "status": "completed"},
            {"id": 2, "title": "Step 2", "status": "in-progress"},
            {"id": 3, "title": "Step 3", "status": "not-started"},
        ]

        with patch.object(_execution_state, "STATE_FILE", state_file):
            _execution_state.save_checkpoint(
                branch="agent/test",
                plan_file="PLAN-test.md",
                current_step=2,
                total_steps=3,
                todo_state=todos,
            )
            result = _execution_state.load_checkpoint()

        assert result is not None
        assert result["todo_state"] == todos

    def test_save_without_todo_state_defaults_to_empty(self, tmp_path: Path) -> None:
        """Verify todo_state defaults to [] when not provided."""
        state_file = tmp_path / "logs" / ".execution-state.json"

        with patch.object(_execution_state, "STATE_FILE", state_file):
            _execution_state.save_checkpoint(
                branch="agent/test",
                plan_file="PLAN-test.md",
                current_step=1,
                total_steps=5,
            )
            result = _execution_state.load_checkpoint()

        assert result is not None
        assert result["todo_state"] == []

    def test_migration_from_old_format(self, tmp_path: Path) -> None:
        """Verify old checkpoint without todo_state gets empty list on load."""
        state_file = tmp_path / "logs" / ".execution-state.json"
        state_file.parent.mkdir(parents=True)
        state_file.write_text(
            json.dumps(
                {
                    "branch": "agent/old",
                    "plan_file": "PLAN-old.md",
                    "current_step": 4,
                    "total_steps": 10,
                    "status": "IN_PROGRESS",
                    "last_updated": "2026-01-01T00:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )

        with patch.object(_execution_state, "STATE_FILE", state_file):
            result = _execution_state.load_checkpoint()

        assert result is not None
        assert result["todo_state"] == []

    def test_partial_completion_recovery(self, tmp_path: Path) -> None:
        """Verify partial todo state is preserved across save/load round-trip."""
        state_file = tmp_path / "logs" / ".execution-state.json"
        todos = [
            {"id": 1, "title": "Audit files", "status": "completed"},
            {"id": 2, "title": "Rewrite instructions", "status": "completed"},
            {"id": 3, "title": "Add lints", "status": "in-progress"},
            {"id": 4, "title": "Write tests", "status": "not-started"},
        ]

        with patch.object(_execution_state, "STATE_FILE", state_file):
            _execution_state.save_checkpoint(
                branch="agent/test",
                plan_file="PLAN-test.md",
                current_step=3,
                total_steps=4,
                todo_state=todos,
            )
            result = _execution_state.load_checkpoint()

        assert result is not None
        assert len(result["todo_state"]) == 4
        completed = [t for t in result["todo_state"] if t["status"] == "completed"]
        in_progress = [t for t in result["todo_state"] if t["status"] == "in-progress"]
        not_started = [t for t in result["todo_state"] if t["status"] == "not-started"]
        assert len(completed) == 2
        assert len(in_progress) == 1
        assert len(not_started) == 1


class TestValidStatuses:
    """Tests for VALID_STATUSES constant and new checkpoint status values."""

    def test_valid_statuses_constant(self) -> None:
        """Assert VALID_STATUSES contains all expected values."""
        expected = {"IN_PROGRESS", "PLAN_COMPLETE", "IMPL_COMPLETE", "REVIEW_COMPLETE", "CI_PENDING", "COMPLETED"}
        assert expected == _execution_state.VALID_STATUSES

    def test_save_and_load_plan_complete(self, tmp_path: Path) -> None:
        """Save with status=PLAN_COMPLETE, load, assert status matches."""
        state_file = tmp_path / "logs" / ".execution-state.json"

        with patch.object(_execution_state, "STATE_FILE", state_file):
            _execution_state.save_checkpoint(
                branch="agent/test",
                plan_file="rec-999",
                current_step=0,
                total_steps=5,
                status="PLAN_COMPLETE",
            )
            result = _execution_state.load_checkpoint()

        assert result is not None
        assert result["status"] == "PLAN_COMPLETE"

    def test_save_and_load_review_complete(self, tmp_path: Path) -> None:
        """Save with status=REVIEW_COMPLETE, load, assert status matches."""
        state_file = tmp_path / "logs" / ".execution-state.json"

        with patch.object(_execution_state, "STATE_FILE", state_file):
            _execution_state.save_checkpoint(
                branch="agent/test",
                plan_file="rec-999",
                current_step=3,
                total_steps=3,
                status="REVIEW_COMPLETE",
            )
            result = _execution_state.load_checkpoint()

        assert result is not None
        assert result["status"] == "REVIEW_COMPLETE"

    def test_save_and_load_ci_pending(self, tmp_path: Path) -> None:
        """Save with status=CI_PENDING, load, assert status matches."""
        state_file = tmp_path / "logs" / ".execution-state.json"

        with patch.object(_execution_state, "STATE_FILE", state_file):
            _execution_state.save_checkpoint(
                branch="agent/test",
                plan_file="rec-999",
                current_step=3,
                total_steps=3,
                status="CI_PENDING",
            )
            result = _execution_state.load_checkpoint()

        assert result is not None
        assert result["status"] == "CI_PENDING"
