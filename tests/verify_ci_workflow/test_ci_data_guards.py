"""Tests for scripts/verify_ci_workflow.py -- the five guards sharing the _VALID_CI_DATA fixture
(VERBATIM split from tests/test_verify_ci_workflow.py, rec-2709 Wave 12).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from scripts.verify_ci_workflow import (
    _check_concurrency,
    _check_fetch_depth,
    _check_full_tier_runtime_lock,
    _check_jobs_and_flags,
    _check_signal_green_needs,
    _check_validate_single_source,
)

# ---------------------------------------------------------------------------
# Shared fixture data for the five guards below
# ---------------------------------------------------------------------------

_VALID_CI_DATA: dict[str, Any] = {
    "jobs": {
        "pr-validate": {
            "if": "github.event_name == 'pull_request'",
            "runs-on": "ubuntu-latest",
            "concurrency": {"group": "pr-validate-${{ github.ref }}", "cancel-in-progress": True},
            "steps": [
                {"uses": "actions/checkout@v4", "with": {"fetch-depth": 0}},
                {"run": "bin/venv-python -m scripts.validate --pre"},
            ],
        },
        "main-validate": {
            "if": "github.event_name == 'push'",
            "runs-on": "ubuntu-latest",
            "steps": [
                {"uses": "actions/checkout@v4", "with": {"fetch-depth": 2}},
                {"uses": "actions/cache@v6", "with": {"key": "pip-${{ hashFiles('requirements.lock') }}"}},
                {
                    "run": "pip install -c requirements.lock -r requirements.txt\n"
                    "pip install -c requirements.lock -r requirements-dev.txt"
                },
                {"run": "bin/venv-python -m scripts.validate"},
            ],
        },
        "terraform-validate": {
            "runs-on": "ubuntu-latest",
            "steps": [{"run": "terraform validate"}],
        },
    }
}

_VALID_CANARY_LOCK_DATA = {
    "jobs": {
        "canary": {
            "steps": [
                {"uses": "actions/cache@v6", "with": {"key": "pip-${{ hashFiles('requirements.lock') }}"}},
                {
                    "run": "pip install -c requirements.lock -r requirements.txt\n"
                    "pip install -c requirements.lock -r requirements-dev.txt"
                },
            ]
        }
    }
}


class TestFullTierRuntimeLock:
    def test_accepts_lock_constrained_jobs(self) -> None:
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.side_effect = [_VALID_CI_DATA, _VALID_CANARY_LOCK_DATA]
            _check_full_tier_runtime_lock()

    @pytest.mark.parametrize("missing", ["constraint", "cache"])
    def test_rejects_missing_main_validate_lock_contract(self, missing: str) -> None:
        import copy

        ci_data = copy.deepcopy(_VALID_CI_DATA)
        steps = ci_data["jobs"]["main-validate"]["steps"]
        if missing == "constraint":
            steps[2]["run"] = "pip install -r requirements.txt\npip install -c requirements.lock -r requirements-dev.txt"
        else:
            steps[1]["with"]["key"] = "pip-runtime"
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.side_effect = [ci_data, _VALID_CANARY_LOCK_DATA]
            with pytest.raises(AssertionError, match="requirements.lock"):
                _check_full_tier_runtime_lock()


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

    def test_fails_when_main_validate_lock_constraint_is_missing(self) -> None:
        import copy

        data = copy.deepcopy(_VALID_CI_DATA)
        data["jobs"]["main-validate"]["steps"][2]["run"] = (
            "pip install -r requirements.txt\npip install -c requirements.lock -r requirements-dev.txt"
        )
        with patch("scripts.verify_ci_workflow._load", return_value=data):
            with pytest.raises(AssertionError, match="requirements.lock"):
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

    def test_fails_when_main_validate_missing_fetch_depth(self) -> None:
        """Decision 159: main-validate must carry fetch-depth: 2 (HEAD~1 must resolve for the
        push-context diff base) -- an absent `with` block is no longer accepted."""
        data = {
            "jobs": {
                "pr-validate": _VALID_CI_DATA["jobs"]["pr-validate"],
                "main-validate": {
                    "if": "github.event_name == 'push'",
                    "runs-on": "ubuntu-latest",
                    "steps": [
                        {"uses": "actions/checkout@v4"},
                        {"run": "bin/venv-python -m scripts.validate"},
                    ],
                },
            }
        }
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = data
            with pytest.raises(AssertionError, match="expected 2"):
                _check_fetch_depth()

    def test_fails_when_main_validate_has_wrong_fetch_depth(self) -> None:
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
            with pytest.raises(AssertionError, match="expected 2"):
                _check_fetch_depth()


# ---------------------------------------------------------------------------
# _check_concurrency (CD.21: ci-runner group ABSENT; VTS-11: pr-validate cancels
# superseded runs on a per-PR key, main-validate does not cancel in-flight runs)
# ---------------------------------------------------------------------------


class TestCheckConcurrencyPassPath:
    def test_passes_when_no_ci_runner_group(self) -> None:
        """Also the VTS-11 happy path: pr-validate's fixture concurrency block (per-PR
        group + cancel-in-progress: True) and main-validate's absent block both satisfy
        _check_concurrency in one pass."""
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = _VALID_CI_DATA
            _check_concurrency()

    def test_passes_with_string_cancel_in_progress_values(self) -> None:
        """cancel-in-progress may be a templated `${{ true }}` expression or a quoted
        "false" string, not just a bare YAML bool -- both must resolve correctly."""
        data = {
            "jobs": {
                "pr-validate": {
                    **_VALID_CI_DATA["jobs"]["pr-validate"],
                    "concurrency": {"group": "pr-validate-${{ github.ref }}", "cancel-in-progress": "${{ true }}"},
                },
                "main-validate": {
                    **_VALID_CI_DATA["jobs"]["main-validate"],
                    "concurrency": {"group": "main-validate-${{ github.ref }}", "cancel-in-progress": "false"},
                },
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

    def test_fails_when_pr_validate_concurrency_block_absent(self) -> None:
        """Inverts the pre-VTS-11 assumption that a fully absent concurrency block passes:
        now that pr-validate must declare a per-PR cancel-in-progress group, an absent block
        fails (on the group-shape assertion, which runs before the cancel-in-progress one)."""
        data = {
            "jobs": {
                "pr-validate": {k: v for k, v in _VALID_CI_DATA["jobs"]["pr-validate"].items() if k != "concurrency"},
                "main-validate": _VALID_CI_DATA["jobs"]["main-validate"],
            }
        }
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = data
            with pytest.raises(AssertionError, match="per-PR keyed"):
                _check_concurrency()

    def test_fails_when_pr_validate_missing_cancel_in_progress(self) -> None:
        data = {
            "jobs": {
                "pr-validate": {
                    **_VALID_CI_DATA["jobs"]["pr-validate"],
                    "concurrency": {"group": "pr-validate-${{ github.ref }}"},
                },
                "main-validate": _VALID_CI_DATA["jobs"]["main-validate"],
            }
        }
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = data
            with pytest.raises(AssertionError, match="cancel-in-progress"):
                _check_concurrency()

    def test_fails_when_main_validate_has_cancel_in_progress(self) -> None:
        data = {
            "jobs": {
                "pr-validate": _VALID_CI_DATA["jobs"]["pr-validate"],
                "main-validate": {
                    **_VALID_CI_DATA["jobs"]["main-validate"],
                    "concurrency": {"group": "main-validate-${{ github.ref }}", "cancel-in-progress": "true"},
                },
            }
        }
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = data
            with pytest.raises(AssertionError, match="cancel-in-progress"):
                _check_concurrency()


# ---------------------------------------------------------------------------
# _check_validate_single_source (Decision 80: ci.yml single-source-of-truth)
# ---------------------------------------------------------------------------


class TestCheckValidateSingleSourcePassPath:
    def test_passes_with_real_workflow_file(self) -> None:
        _check_validate_single_source()

    def test_passes_with_valid_ci_data(self) -> None:
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = _VALID_CI_DATA
            _check_validate_single_source()


class TestCheckValidateSingleSourceFailPath:
    def test_fails_when_check_step_bypasses_validate(self) -> None:
        data = {
            "jobs": {
                "pr-validate": {
                    "if": "github.event_name == 'pull_request'",
                    "runs-on": "ubuntu-latest",
                    "steps": [
                        {"uses": "actions/checkout@v4", "with": {"fetch-depth": 0}},
                        {"run": "bin/venv-python -m scripts.validate_bogus --pre"},
                    ],
                },
                "main-validate": _VALID_CI_DATA["jobs"]["main-validate"],
            }
        }
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = data
            with pytest.raises(AssertionError, match="scripts.validate_bogus"):
                _check_validate_single_source()

    def test_fails_when_check_step_invoked_as_script_path(self) -> None:
        data = {
            "jobs": {
                "pr-validate": {
                    "if": "github.event_name == 'pull_request'",
                    "runs-on": "ubuntu-latest",
                    "steps": [{"run": "bin/venv-python scripts/verify_something.py"}],
                },
            }
        }
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = data
            with pytest.raises(AssertionError, match="scripts.verify_something"):
                _check_validate_single_source()


# ---------------------------------------------------------------------------
# _check_signal_green_needs (Decision 80: signal-green must gate on every
# PR-gating job, including a job with no `if` key)
# ---------------------------------------------------------------------------


class TestCheckSignalGreenNeedsPassPath:
    def test_passes_with_real_workflow_file(self) -> None:
        _check_signal_green_needs()

    def test_passes_when_all_pr_gating_jobs_are_needed(self) -> None:
        data = {
            "jobs": {
                "pr-validate": _VALID_CI_DATA["jobs"]["pr-validate"],
                "main-validate": _VALID_CI_DATA["jobs"]["main-validate"],
                "terraform-validate": _VALID_CI_DATA["jobs"]["terraform-validate"],
                "signal-green": {"needs": ["pr-validate", "terraform-validate"]},
            }
        }
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = data
            _check_signal_green_needs()


class TestCheckSignalGreenNeedsFailPath:
    def test_fails_when_signal_green_job_missing(self) -> None:
        data = {"jobs": {"pr-validate": _VALID_CI_DATA["jobs"]["pr-validate"]}}
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = data
            with pytest.raises(AssertionError, match="signal-green job missing"):
                _check_signal_green_needs()

    def test_fails_when_pr_gating_job_missing_from_needs(self) -> None:
        data = {
            "jobs": {
                "pr-validate": _VALID_CI_DATA["jobs"]["pr-validate"],
                "main-validate": _VALID_CI_DATA["jobs"]["main-validate"],
                "terraform-validate": _VALID_CI_DATA["jobs"]["terraform-validate"],
                "signal-green": {"needs": ["pr-validate"]},
            }
        }
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = data
            with pytest.raises(AssertionError, match="terraform-validate"):
                _check_signal_green_needs()

    def test_fails_when_no_if_job_missing_from_needs(self) -> None:
        """A job with NO `if` key runs on every event (including pull_request), so it is
        PR-gating -- a naive `'pull_request' in if_str` test would miss this branch."""
        data = {
            "jobs": {
                "pr-validate": _VALID_CI_DATA["jobs"]["pr-validate"],
                "main-validate": _VALID_CI_DATA["jobs"]["main-validate"],
                "no-if-job": {"runs-on": "ubuntu-latest", "steps": [{"run": "echo hi"}]},
                "signal-green": {"needs": ["pr-validate"]},
            }
        }
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = data
            with pytest.raises(AssertionError, match="no-if-job"):
                _check_signal_green_needs()

    def test_fails_when_neither_push_nor_pull_request_job_missing_from_needs(self) -> None:
        """An `if` mentioning neither push nor pull_request (e.g. workflow_dispatch-only)
        defaults to PR-gating (conservative direction) -- covers _admits_pull_request's
        final fallback branch."""
        data = {
            "jobs": {
                "pr-validate": _VALID_CI_DATA["jobs"]["pr-validate"],
                "main-validate": _VALID_CI_DATA["jobs"]["main-validate"],
                "dispatch-only-job": {
                    "if": "github.event_name == 'workflow_dispatch'",
                    "runs-on": "ubuntu-latest",
                    "steps": [{"run": "echo hi"}],
                },
                "signal-green": {"needs": ["pr-validate"]},
            }
        }
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = data
            with pytest.raises(AssertionError, match="dispatch-only-job"):
                _check_signal_green_needs()

    def test_passes_when_needs_is_a_single_string(self) -> None:
        """signal-green.needs may be a bare string (single dependency) rather than a list."""
        data = {
            "jobs": {
                "pr-validate": _VALID_CI_DATA["jobs"]["pr-validate"],
                "signal-green": {"needs": "pr-validate"},
            }
        }
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = data
            _check_signal_green_needs()
