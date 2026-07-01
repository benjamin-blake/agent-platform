"""Tests for scripts/verify_ci_workflow guards."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from scripts.verify_ci_workflow import (
    _check_apply_rca_fallback,
    _check_canary,
    _check_ci_rca_filter,
    _check_concurrency,
    _check_fetch_depth,
    _check_jobs_and_flags,
)

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


# ---------------------------------------------------------------------------
# Shared fixture data for the four newly-wired guards
# ---------------------------------------------------------------------------

_VALID_CI_DATA: dict[str, Any] = {
    "jobs": {
        "pr-validate": {
            "if": "github.event_name == 'pull_request'",
            "runs-on": "ubuntu-latest",
            "steps": [
                {"uses": "actions/checkout@v4", "with": {"fetch-depth": 0}},
                {"run": "bin/venv-python -m scripts.validate --pre"},
            ],
        },
        "main-validate": {
            "if": "github.event_name == 'push'",
            "runs-on": "ubuntu-latest",
            "steps": [
                {"uses": "actions/checkout@v4"},
                {"run": "bin/venv-python -m scripts.validate"},
            ],
        },
        "terraform-validate": {
            "runs-on": "ubuntu-latest",
            "steps": [{"run": "terraform validate"}],
        },
    }
}

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
# _check_jobs_and_flags
# ---------------------------------------------------------------------------


class TestCheckJobsAndFlagsPassPath:
    def test_passes_with_valid_ci_data(self) -> None:
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = _VALID_CI_DATA
            _check_jobs_and_flags()


class TestCheckJobsAndFlagsFailPath:
    def test_fails_when_pr_validate_missing(self) -> None:
        data = {
            "jobs": {
                "main-validate": _VALID_CI_DATA["jobs"]["main-validate"],
            }
        }
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = data
            with pytest.raises(AssertionError, match="pr-validate job missing"):
                _check_jobs_and_flags()

    def test_fails_when_pr_validate_missing_pre_flag(self) -> None:
        data = {
            "jobs": {
                "pr-validate": {
                    "if": "github.event_name == 'pull_request'",
                    "runs-on": "ubuntu-latest",
                    "steps": [
                        {"uses": "actions/checkout@v4", "with": {"fetch-depth": 0}},
                        {"run": "bin/venv-python -m scripts.validate"},
                    ],
                },
                "main-validate": _VALID_CI_DATA["jobs"]["main-validate"],
            }
        }
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = data
            with pytest.raises(AssertionError, match="--pre"):
                _check_jobs_and_flags()


# ---------------------------------------------------------------------------
# _check_fetch_depth
# ---------------------------------------------------------------------------


class TestCheckFetchDepthPassPath:
    def test_passes_with_valid_ci_data(self) -> None:
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = _VALID_CI_DATA
            _check_fetch_depth()


class TestCheckFetchDepthFailPath:
    def test_fails_when_pr_validate_missing_fetch_depth(self) -> None:
        data = {
            "jobs": {
                "pr-validate": {
                    "if": "github.event_name == 'pull_request'",
                    "runs-on": "ubuntu-latest",
                    "steps": [
                        {"uses": "actions/checkout@v4"},
                        {"run": "bin/venv-python -m scripts.validate --pre"},
                    ],
                },
                "main-validate": _VALID_CI_DATA["jobs"]["main-validate"],
            }
        }
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = data
            with pytest.raises(AssertionError, match="fetch-depth"):
                _check_fetch_depth()

    def test_fails_when_main_validate_has_fetch_depth(self) -> None:
        data = {
            "jobs": {
                "pr-validate": _VALID_CI_DATA["jobs"]["pr-validate"],
                "main-validate": {
                    "if": "github.event_name == 'push'",
                    "runs-on": "ubuntu-latest",
                    "steps": [
                        {"uses": "actions/checkout@v4", "with": {"fetch-depth": 0}},
                        {"run": "bin/venv-python -m scripts.validate"},
                    ],
                },
            }
        }
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = data
            with pytest.raises(AssertionError, match="unexpected fetch-depth"):
                _check_fetch_depth()


# ---------------------------------------------------------------------------
# _check_concurrency (CD.21: assert ci-runner group is ABSENT)
# ---------------------------------------------------------------------------


class TestCheckConcurrencyPassPath:
    def test_passes_when_no_ci_runner_group(self) -> None:
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = _VALID_CI_DATA
            _check_concurrency()

    def test_passes_when_concurrency_block_absent(self) -> None:
        data = {
            "jobs": {
                "pr-validate": {**_VALID_CI_DATA["jobs"]["pr-validate"]},
                "main-validate": {**_VALID_CI_DATA["jobs"]["main-validate"]},
            }
        }
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = data
            _check_concurrency()


class TestCheckConcurrencyFailPath:
    def test_fails_when_pr_validate_still_has_ci_runner(self) -> None:
        data = {
            "jobs": {
                "pr-validate": {
                    **_VALID_CI_DATA["jobs"]["pr-validate"],
                    "concurrency": {"group": "ci-runner", "cancel-in-progress": False},
                },
                "main-validate": _VALID_CI_DATA["jobs"]["main-validate"],
            }
        }
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = data
            with pytest.raises(AssertionError, match="ci-runner"):
                _check_concurrency()

    def test_fails_when_main_validate_still_has_ci_runner(self) -> None:
        data = {
            "jobs": {
                "pr-validate": _VALID_CI_DATA["jobs"]["pr-validate"],
                "main-validate": {
                    **_VALID_CI_DATA["jobs"]["main-validate"],
                    "concurrency": {"group": "ci-runner", "cancel-in-progress": False},
                },
            }
        }
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = data
            with pytest.raises(AssertionError, match="ci-runner"):
                _check_concurrency()


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
# _check_apply_rca_fallback (PLAN-gated-apply-rca-trigger)
# ---------------------------------------------------------------------------

_DISPATCH_STEP: dict[str, Any] = {
    "name": "Self-dispatch ci-rca on re-run failure (workflow_run re-run gap)",
    "if": "${{ failure() && github.run_attempt != '1' }}",
    "run": "gh workflow run ci-rca.yml -f run_id=${{ github.run_id }}",
}

_VALID_APPLY_SANDBOX_DATA: dict[str, Any] = {
    "jobs": {
        "apply-sandbox": {
            "permissions": {"id-token": "write", "contents": "read", "actions": "write"},
            "steps": [
                {"run": "terraform apply plan.bin"},
                _DISPATCH_STEP,
            ],
        },
        "gated-apply": {
            "permissions": {"id-token": "write", "contents": "read", "actions": "write"},
            "steps": [
                {"run": "terraform apply plan.bin"},
                _DISPATCH_STEP,
            ],
        },
    }
}


class TestCheckApplyRcaFallbackPassPath:
    def test_passes_with_real_workflow_file(self) -> None:
        _check_apply_rca_fallback()


class TestCheckApplyRcaFallbackFailPath:
    def test_apply_rca_fallback_missing_step_fails(self) -> None:
        data = {
            "jobs": {
                "apply-sandbox": {
                    "permissions": {**_VALID_APPLY_SANDBOX_DATA["jobs"]["apply-sandbox"]["permissions"]},
                    "steps": [{"run": "terraform apply plan.bin"}],
                },
                "gated-apply": _VALID_APPLY_SANDBOX_DATA["jobs"]["gated-apply"],
            }
        }
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = data
            with pytest.raises(AssertionError, match="apply-sandbox is missing"):
                _check_apply_rca_fallback()

    def test_apply_rca_fallback_missing_permission_fails(self) -> None:
        data = {
            "jobs": {
                "apply-sandbox": _VALID_APPLY_SANDBOX_DATA["jobs"]["apply-sandbox"],
                "gated-apply": {
                    "permissions": {"id-token": "write", "contents": "read"},
                    "steps": [
                        {"run": "terraform apply plan.bin"},
                        _DISPATCH_STEP,
                    ],
                },
            }
        }
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = data
            with pytest.raises(AssertionError, match="gated-apply is missing 'actions: write'"):
                _check_apply_rca_fallback()

    def test_apply_rca_fallback_missing_step_fails_for_gated_apply(self) -> None:
        data = {
            "jobs": {
                "apply-sandbox": _VALID_APPLY_SANDBOX_DATA["jobs"]["apply-sandbox"],
                "gated-apply": {
                    "permissions": {**_VALID_APPLY_SANDBOX_DATA["jobs"]["gated-apply"]["permissions"]},
                    "steps": [{"run": "terraform apply plan.bin"}],
                },
            }
        }
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = data
            with pytest.raises(AssertionError, match="gated-apply is missing"):
                _check_apply_rca_fallback()
