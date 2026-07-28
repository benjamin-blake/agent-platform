"""Tests for scripts/verify_ci_workflow.py -- ci-rca-filter guard + canary guard concern
(VERBATIM split from tests/test_verify_ci_workflow.py, rec-2709 Wave 12).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from scripts.verify_ci_workflow import _check_canary, _check_ci_rca_fetch_classification, _check_ci_rca_filter

_REAL_RCA_IF = (
    "github.event_name == 'workflow_dispatch' || "
    "(github.event.workflow_run.conclusion == 'failure' "
    "&& github.event.workflow_run.head_repository.full_name == github.repository "
    "&& github.event.workflow_run.head_branch == github.event.repository.default_branch)"
)

_REQUIRED_WORKFLOWS = ["CI", "Main Canary", "terraform-apply-sandbox", "rec-autoclose", "deploy-ducklake-lambdas"]

_REAL_RCA_DATA = {
    "on": {"workflow_run": {"workflows": list(_REQUIRED_WORKFLOWS), "types": ["completed"]}},
    "jobs": {"rca": {"if": _REAL_RCA_IF, "runs-on": "ubuntu-latest", "steps": []}},
}

_REAL_CANARY_DATA = {"name": "Main Canary"}

_FILED_MARKER_CONTENT = "## Step 6: Report\n\nFILED: rec-NNN or FILED: none\n"


class TestCheckCiRcaFilterPassPath:
    def test_passes_with_real_workflow_files(self) -> None:
        _check_ci_rca_filter()


class TestCheckCiRcaFilterRequiredSet:
    """PLAN-ci-rca-ops-plane-coverage: the required-membership floor closes the pre-existing
    hole where terraform-apply-sandbox sat in the filter unguarded (rec-2849). One drop-one-entry
    case per required workflow, plus a duplicate-entry case."""

    @pytest.mark.parametrize("dropped", _REQUIRED_WORKFLOWS)
    def test_fails_when_required_entry_missing(self, dropped: str) -> None:
        workflows = [w for w in _REQUIRED_WORKFLOWS if w != dropped]
        rca_data = {
            "on": {"workflow_run": {"workflows": workflows}},
            "jobs": {"rca": {"if": _REAL_RCA_IF, "steps": []}},
        }
        with (
            patch("scripts.verify_ci_workflow._load") as mock_load,
            patch("scripts.verify_ci_workflow.Path") as mock_path,
        ):
            mock_load.side_effect = lambda p: _REAL_CANARY_DATA if "canary" in p else rca_data
            mock_path.return_value.read_text.return_value = _FILED_MARKER_CONTENT
            with pytest.raises(AssertionError, match="missing required entries"):
                _check_ci_rca_filter()

    def test_fails_on_duplicate_entry(self) -> None:
        workflows = [*_REQUIRED_WORKFLOWS, "CI"]
        rca_data = {
            "on": {"workflow_run": {"workflows": workflows}},
            "jobs": {"rca": {"if": _REAL_RCA_IF, "steps": []}},
        }
        with (
            patch("scripts.verify_ci_workflow._load") as mock_load,
            patch("scripts.verify_ci_workflow.Path") as mock_path,
        ):
            mock_load.side_effect = lambda p: _REAL_CANARY_DATA if "canary" in p else rca_data
            mock_path.return_value.read_text.return_value = _FILED_MARKER_CONTENT
            with pytest.raises(AssertionError, match="duplicate entries"):
                _check_ci_rca_filter()


class TestCheckCiRcaFilterMainBranchGate:
    def test_fails_when_head_branch_missing(self) -> None:
        rca_data_no_gate = {
            "on": {"workflow_run": {"workflows": list(_REQUIRED_WORKFLOWS)}},
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
            "on": {"workflow_run": {"workflows": list(_REQUIRED_WORKFLOWS)}},
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
            "steps": [
                {"uses": "actions/cache@v6", "with": {"key": "pip-${{ hashFiles('requirements.lock') }}"}},
                {
                    "run": "pip install -c requirements.lock -r requirements.txt\n"
                    "pip install -c requirements.lock -r requirements-dev.txt"
                },
                {"run": "bin/venv-python -m scripts.validate"},
            ],
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


# ---------------------------------------------------------------------------
# _check_ci_rca_fetch_classification (rec-2857 forward fix -- ALLOWLIST guard)
# ---------------------------------------------------------------------------

_PASSING_FETCH_STEP_BODY = (
    'RUN_ID="${{ steps.meta.outputs.run_id }}"\n'
    'bin/venv-python -m scripts.ci_rca.fetch_logs --run-id "$RUN_ID" '
    '--repo "${{ github.repository }}" --out /tmp/ci-rca-failed.log\n'
    "test -s /tmp/ci-rca-failed.log\n"
)


def _rca_data_with_fetch_step(run_body: str) -> dict[str, Any]:
    return {
        "jobs": {
            "rca": {
                "steps": [
                    {"name": "Resolve run metadata"},
                    {"name": "Fetch failed run logs", "run": run_body},
                    {"name": "Fetch jobs JSON"},
                ]
            }
        }
    }


class TestCheckCiRcaFetchClassification:
    def test_passes_on_real_post_change_step_body(self) -> None:
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = _rca_data_with_fetch_step(_PASSING_FETCH_STEP_BODY)
            _check_ci_rca_fetch_classification()

    def test_rejects_literal_historical_grep(self) -> None:
        body = _PASSING_FETCH_STEP_BODY + (
            "TRANSIENT_ERROR_RE='failed to get jobs|failed to get run|HTTP 5[0-9][0-9]|Service Unavailable'\n"
            'grep -qiE "$TRANSIENT_ERROR_RE" /tmp/ci-rca-failed.log\n'
        )
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = _rca_data_with_fetch_step(body)
            with pytest.raises(AssertionError, match="pattern-matching construct"):
                _check_ci_rca_fetch_classification()

    def test_rejects_renamed_pattern_variable(self) -> None:
        body = _PASSING_FETCH_STEP_BODY + ("PATTERN_X='HTTP 5[0-9][0-9]'\ngrep -qiE \"$PATTERN_X\" /tmp/ci-rca-failed.log\n")
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = _rca_data_with_fetch_step(body)
            with pytest.raises(AssertionError, match="pattern-matching construct"):
                _check_ci_rca_fetch_classification()

    def test_rejects_renamed_log_path_variable(self) -> None:
        body = _PASSING_FETCH_STEP_BODY + ('LOGFILE=/tmp/ci-rca-failed.log\ngrep -qiE "HTTP 5" "$LOGFILE"\n')
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = _rca_data_with_fetch_step(body)
            with pytest.raises(AssertionError, match="pattern-matching construct"):
                _check_ci_rca_fetch_classification()

    def test_rejects_case_statement_shape_a_blocklist_would_miss(self) -> None:
        body = _PASSING_FETCH_STEP_BODY + ('case "$(cat /tmp/ci-rca-failed.log)" in\n  *"HTTP 5"*) exit 1 ;;\nesac\n')
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = _rca_data_with_fetch_step(body)
            with pytest.raises(AssertionError, match="pattern-matching construct"):
                _check_ci_rca_fetch_classification()

    def test_rejects_awk_shape_a_blocklist_would_miss(self) -> None:
        body = _PASSING_FETCH_STEP_BODY + ("awk '/HTTP 5/{exit 1}' /tmp/ci-rca-failed.log\n")
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = _rca_data_with_fetch_step(body)
            with pytest.raises(AssertionError, match="pattern-matching construct"):
                _check_ci_rca_fetch_classification()

    def test_rejects_inline_python_c_shape_a_blocklist_would_miss(self) -> None:
        body = _PASSING_FETCH_STEP_BODY + (
            "python3 -c \"import re,sys; sys.exit(1 if re.search('HTTP 5', open('/tmp/ci-rca-failed.log').read()) else 0)\"\n"
        )
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = _rca_data_with_fetch_step(body)
            with pytest.raises(AssertionError, match="pattern-matching construct"):
                _check_ci_rca_fetch_classification()

    def test_rejects_missing_module_invocation(self) -> None:
        body = (
            'RUN_ID="${{ steps.meta.outputs.run_id }}"\n'
            'echo "no module call here" > /tmp/ci-rca-failed.log\n'
            "test -s /tmp/ci-rca-failed.log\n"
        )
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = _rca_data_with_fetch_step(body)
            with pytest.raises(AssertionError, match="no longer invokes scripts.ci_rca.fetch_logs"):
                _check_ci_rca_fetch_classification()

    def test_fails_when_step_not_found(self) -> None:
        rca_data = {"jobs": {"rca": {"steps": [{"name": "Some other step", "run": "echo hi"}]}}}
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = rca_data
            with pytest.raises(AssertionError, match="not found in job"):
                _check_ci_rca_fetch_classification()
