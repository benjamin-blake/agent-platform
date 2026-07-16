"""Tests for scripts/verify_ci_workflow.py -- apply-rca-fallback guard + terraform-apply-
concurrency guard concern (VERBATIM split from tests/test_verify_ci_workflow.py, rec-2709 Wave 12).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from scripts.verify_ci_workflow import _check_apply_rca_fallback, _check_terraform_apply_concurrency

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


# ---------------------------------------------------------------------------
# _check_terraform_apply_concurrency (T2.35 hardening -- event-keyed concurrency group)
# ---------------------------------------------------------------------------

_VALID_APPLY_CONCURRENCY_GROUP = (
    "${{ github.event_name == 'pull_request' && format('terraform-apply-plan-pr-{0}', "
    "github.event.pull_request.number) || 'terraform-apply-sandbox' }}"
)

_VALID_APPLY_CONCURRENCY_DATA: dict[str, Any] = {
    "concurrency": {
        "group": _VALID_APPLY_CONCURRENCY_GROUP,
        "cancel-in-progress": "${{ github.event_name == 'pull_request' }}",
    }
}

_VALID_RECONCILE_CONCURRENCY_DATA: dict[str, Any] = {
    "concurrency": {
        "group": "terraform-apply-sandbox",
        "cancel-in-progress": False,
    }
}


def _mock_load_for(apply_data: dict[str, Any], reconcile_data: dict[str, Any]) -> Any:
    return lambda p: reconcile_data if "reconcile" in p else apply_data


class TestCheckTerraformApplyConcurrencyPassPath:
    def test_passes_with_real_workflow_files(self) -> None:
        _check_terraform_apply_concurrency()

    def test_passes_with_valid_data(self) -> None:
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.side_effect = _mock_load_for(_VALID_APPLY_CONCURRENCY_DATA, _VALID_RECONCILE_CONCURRENCY_DATA)
            _check_terraform_apply_concurrency()


class TestCheckTerraformApplyConcurrencyFailPath:
    def test_fails_on_non_conditional_shared_everything_group(self) -> None:
        apply_data = {"concurrency": {"group": "terraform-apply-sandbox", "cancel-in-progress": False}}
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.side_effect = _mock_load_for(apply_data, _VALID_RECONCILE_CONCURRENCY_DATA)
            with pytest.raises(AssertionError, match="not event-keyed"):
                _check_terraform_apply_concurrency()

    def test_fails_on_missing_per_pr_key(self) -> None:
        apply_data = {
            "concurrency": {
                "group": (
                    "${{ github.event_name == 'pull_request' && 'terraform-apply-sandbox' || 'terraform-apply-sandbox' }}"
                ),
                "cancel-in-progress": "${{ github.event_name == 'pull_request' }}",
            }
        }
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.side_effect = _mock_load_for(apply_data, _VALID_RECONCILE_CONCURRENCY_DATA)
            with pytest.raises(AssertionError, match="per-PR format key"):
                _check_terraform_apply_concurrency()

    def test_fails_on_missing_shared_key(self) -> None:
        apply_data = {
            "concurrency": {
                "group": (
                    "${{ github.event_name == 'pull_request' && format('terraform-apply-plan-pr-{0}', "
                    "github.event.pull_request.number) || 'some-other-key' }}"
                ),
                "cancel-in-progress": "${{ github.event_name == 'pull_request' }}",
            }
        }
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.side_effect = _mock_load_for(apply_data, _VALID_RECONCILE_CONCURRENCY_DATA)
            with pytest.raises(AssertionError, match="shared push/dispatch key"):
                _check_terraform_apply_concurrency()

    def test_fails_when_cancel_in_progress_not_gated_on_pull_request(self) -> None:
        apply_data = {
            "concurrency": {
                "group": _VALID_APPLY_CONCURRENCY_GROUP,
                "cancel-in-progress": False,
            }
        }
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.side_effect = _mock_load_for(apply_data, _VALID_RECONCILE_CONCURRENCY_DATA)
            with pytest.raises(AssertionError, match="not gated on pull_request"):
                _check_terraform_apply_concurrency()

    def test_fails_when_cancel_in_progress_unconditionally_true(self) -> None:
        apply_data = {
            "concurrency": {
                "group": _VALID_APPLY_CONCURRENCY_GROUP,
                "cancel-in-progress": True,
            }
        }
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.side_effect = _mock_load_for(apply_data, _VALID_RECONCILE_CONCURRENCY_DATA)
            with pytest.raises(AssertionError, match="not gated on pull_request"):
                _check_terraform_apply_concurrency()

    def test_fails_when_reconcile_in_different_group(self) -> None:
        reconcile_data = {"concurrency": {"group": "some-other-group", "cancel-in-progress": False}}
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.side_effect = _mock_load_for(_VALID_APPLY_CONCURRENCY_DATA, reconcile_data)
            with pytest.raises(AssertionError, match="no longer shares"):
                _check_terraform_apply_concurrency()
