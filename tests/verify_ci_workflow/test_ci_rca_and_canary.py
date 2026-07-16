"""Tests for scripts/verify_ci_workflow.py -- ci-rca-filter guard + canary guard concern
(VERBATIM split from tests/test_verify_ci_workflow.py, rec-2709 Wave 12).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from scripts.verify_ci_workflow import _check_canary, _check_ci_rca_filter

_REAL_RCA_IF = (
    "github.event_name == 'workflow_dispatch' || "
    "(github.event.workflow_run.conclusion == 'failure' "
    "&& github.event.workflow_run.head_repository.full_name == github.repository "
    "&& github.event.workflow_run.head_branch == github.event.repository.default_branch)"
)

_REAL_RCA_DATA = {
    "on": {"workflow_run": {"workflows": ["CI", "Main Canary"], "types": ["completed"]}},
    "jobs": {"rca": {"if": _REAL_RCA_IF, "runs-on": "ubuntu-latest", "steps": []}},
}

_REAL_CANARY_DATA = {"name": "Main Canary"}

_FILED_MARKER_CONTENT = "## Step 6: Report\n\nFILED: rec-NNN or FILED: none\n"


class TestCheckCiRcaFilterPassPath:
    def test_passes_with_real_workflow_files(self) -> None:
        _check_ci_rca_filter()


class TestCheckCiRcaFilterMainBranchGate:
    def test_fails_when_head_branch_missing(self) -> None:
        rca_data_no_gate = {
            "on": {"workflow_run": {"workflows": ["CI", "Main Canary"]}},
            "jobs": {
                "rca": {
                    "if": (
                        "github.event_name == 'workflow_dispatch' || "
                        "(github.event.workflow_run.conclusion == 'failure' "
                        "&& github.event.workflow_run.head_repository.full_name == github.repository)"
                    ),
                    "steps": [],
                }
            },
        }
        with (
            patch("scripts.verify_ci_workflow._load") as mock_load,
            patch("scripts.verify_ci_workflow.Path") as mock_path,
        ):
            mock_load.side_effect = lambda p: _REAL_CANARY_DATA if "canary" in p else rca_data_no_gate
            mock_path.return_value.read_text.return_value = _FILED_MARKER_CONTENT
            with pytest.raises(AssertionError, match="head_branch"):
                _check_ci_rca_filter()

    def test_fails_when_default_branch_missing(self) -> None:
        rca_data_partial_gate = {
            "on": {"workflow_run": {"workflows": ["CI", "Main Canary"]}},
            "jobs": {
                "rca": {
                    "if": (
                        "github.event_name == 'workflow_dispatch' || "
                        "(github.event.workflow_run.conclusion == 'failure' "
                        "&& github.event.workflow_run.head_branch == 'main')"
                    ),
                    "steps": [],
                }
            },
        }
        with (
            patch("scripts.verify_ci_workflow._load") as mock_load,
            patch("scripts.verify_ci_workflow.Path") as mock_path,
        ):
            mock_load.side_effect = lambda p: _REAL_CANARY_DATA if "canary" in p else rca_data_partial_gate
            mock_path.return_value.read_text.return_value = _FILED_MARKER_CONTENT
            with pytest.raises(AssertionError, match="default_branch"):
                _check_ci_rca_filter()


class TestCheckCiRcaFilterFiledMarker:
    def test_fails_when_filed_marker_missing_from_agent_doc(self) -> None:
        with (
            patch("scripts.verify_ci_workflow._load") as mock_load,
            patch("scripts.verify_ci_workflow.Path") as mock_path,
        ):
            mock_load.side_effect = lambda p: _REAL_CANARY_DATA if "canary" in p else _REAL_RCA_DATA
            mock_path.return_value.read_text.return_value = "## Step 6: Report\n\nPrint a brief summary.\n"
            with pytest.raises(AssertionError, match="FILED:"):
                _check_ci_rca_filter()

    def test_passes_when_filed_marker_present(self) -> None:
        with (
            patch("scripts.verify_ci_workflow._load") as mock_load,
            patch("scripts.verify_ci_workflow.Path") as mock_path,
        ):
            mock_load.side_effect = lambda p: _REAL_CANARY_DATA if "canary" in p else _REAL_RCA_DATA
            mock_path.return_value.read_text.return_value = _FILED_MARKER_CONTENT
            _check_ci_rca_filter()


_VALID_CANARY_DATA: dict[str, Any] = {
    "name": "Main Canary",
    "on": {
        "schedule": [{"cron": "0 */3 * * *"}],
        "workflow_dispatch": {},
    },
    "jobs": {
        "canary": {
            "runs-on": "ubuntu-latest",
            "steps": [{"run": "bin/venv-python -m scripts.validate"}],
        }
    },
}


# ---------------------------------------------------------------------------
# _check_canary (CD.21: assert ubuntu-latest, not self-hosted)
# ---------------------------------------------------------------------------


class TestCheckCanaryPassPath:
    def test_passes_with_ubuntu_latest(self) -> None:
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = _VALID_CANARY_DATA
            _check_canary()


class TestCheckCanaryFailPath:
    def test_fails_when_canary_still_uses_self_hosted(self) -> None:
        data = {
            "name": "Main Canary",
            "on": {
                "schedule": [{"cron": "0 */3 * * *"}],
                "workflow_dispatch": {},
            },
            "jobs": {
                "canary": {
                    "runs-on": ["self-hosted", "linux"],
                    "steps": [{"run": "bin/venv-python -m scripts.validate"}],
                }
            },
        }
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = data
            with pytest.raises(AssertionError, match="ubuntu-latest"):
                _check_canary()

    def test_fails_when_canary_steps_reference_pre(self) -> None:
        data = {
            "name": "Main Canary",
            "on": {
                "schedule": [{"cron": "0 */3 * * *"}],
                "workflow_dispatch": {},
            },
            "jobs": {
                "canary": {
                    "runs-on": "ubuntu-latest",
                    "steps": [{"run": "bin/venv-python -m scripts.validate --pre"}],
                }
            },
        }
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = data
            with pytest.raises(AssertionError, match="--pre"):
                _check_canary()
