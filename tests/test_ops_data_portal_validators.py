"""Unit tests for wave-2 write-time validators and compute_automatable in ops_data_portal."""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from scripts.ops_data_portal import (
    _validate_context_length,
    _validate_file_path,
    compute_automatable,
    file_rec,
)

# ---------------------------------------------------------------------------
# _validate_file_path
# ---------------------------------------------------------------------------


def test_file_path_rejects_absolute_unix():
    with pytest.raises(ValueError, match="absolute Unix"):
        _validate_file_path("/abs/path/file.py")


def test_file_path_rejects_absolute_windows():
    with pytest.raises(ValueError, match="absolute Windows"):
        _validate_file_path("C:\\path\\file.py")


def test_file_path_rejects_backslash_separator():
    with pytest.raises(ValueError, match="backslash"):
        _validate_file_path("scripts\\module.py")


def test_file_path_accepts_relative():
    _validate_file_path("scripts/module.py")  # must not raise


def test_file_path_accepts_nonexistent_relative():
    _validate_file_path("scripts/future_file.py")  # no existence check; must not raise


# ---------------------------------------------------------------------------
# _validate_context_length
# ---------------------------------------------------------------------------


def test_context_length_rejects_short():
    with pytest.raises(ValueError, match="80"):
        _validate_context_length("fix bug")


def test_context_length_accepts_80_chars():
    _validate_context_length("x" * 80)  # exactly 80 chars -- must not raise


# ---------------------------------------------------------------------------
# lint_acceptance_command wired into file_rec
# ---------------------------------------------------------------------------


def test_acceptance_lint_wired_into_file_rec():
    """file_rec raises ValueError when acceptance contains a banned python -c pattern."""
    long_context = "This recommendation exists because the system needs improvement to handle edge cases."
    fields = {
        "title": "Test recommendation title",
        "file": "scripts/some_module.py",
        "context": long_context,
        "acceptance": 'python -c "x=1"',
        "effort": "S",
        "priority": "Low",
        "source": "manual",
        "status": "open",
    }
    with patch("scripts.ops_data_portal.validate_source"):
        with pytest.raises(ValueError, match="python -c"):
            file_rec(fields)


# ---------------------------------------------------------------------------
# compute_automatable
# ---------------------------------------------------------------------------


def test_compute_automatable_boundary_file():
    """Files matching a boundary pattern return False regardless of risk score."""
    # "scripts/executor/" is in the boundary_patterns of config/agent/executor/capabilities.yaml
    result = compute_automatable("scripts/executor/some_tool.py", "S")
    assert result is False


def test_compute_automatable_high_risk_score():
    """R > maturity_ceiling returns False."""
    with patch("scripts.ops_data_portal._compute_risk_score", return_value=999.0):
        result = compute_automatable("scripts/some_new_module.py", "M")
    assert result is False


def test_compute_automatable_valid():
    """Normal file with R <= maturity_ceiling returns True."""
    with patch("scripts.ops_data_portal._compute_risk_score", return_value=0.5):
        result = compute_automatable("scripts/some_new_module.py", "XS")
    assert result is True


# ---------------------------------------------------------------------------
# automatable override warning in file_rec
# ---------------------------------------------------------------------------


def test_automatable_override_warning(caplog):
    """Caller-supplied automatable=True overridden to False by formula; WARNING emitted."""
    long_context = "This recommendation exists because the system needs improvement to handle edge cases."
    fields = {
        "title": "Test boundary recommendation",
        "file": "scripts/executor/some_tool.py",  # boundary file -> compute_automatable returns False
        "context": long_context,
        "acceptance": "grep -q 'pattern' scripts/executor/some_tool.py",
        "effort": "S",
        "priority": "Low",
        "source": "manual",
        "status": "open",
        "automatable": True,  # caller supplies True; formula will derive False (boundary file)
    }
    with (
        patch("scripts.ops_data_portal.validate_source"),
        patch("scripts.ops_data_portal._next_id", return_value="rec-999"),
        patch("scripts.ops_data_portal.Recommendation.model_validate"),
        patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}),
        patch("scripts.ops_data_portal._append_to_local_jsonl"),
        patch("scripts.ops_data_portal._sync_table"),
        caplog.at_level(logging.WARNING, logger="scripts.ops_data_portal"),
    ):
        file_rec(fields)

    warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("automatable" in str(m) for m in warning_msgs), (
        f"Expected automatable override WARNING in logs; got: {warning_msgs}"
    )
