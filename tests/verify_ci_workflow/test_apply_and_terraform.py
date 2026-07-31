"""Tests for scripts/verify_ci_workflow.py -- apply-rca-fallback guard + terraform-apply-
concurrency guard concern (VERBATIM split from tests/test_verify_ci_workflow.py, rec-2709 Wave 12),
plus the recovery-workflow-topology guard (rec-2847 part (c)).
"""

from __future__ import annotations

import copy
from typing import Any
from unittest.mock import patch

import pytest

from scripts.verify_ci_workflow import (
    _check_apply_rca_fallback,
    _check_recovery_workflow_topology,
    _check_terraform_apply_concurrency,
)

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


# ---------------------------------------------------------------------------
# _check_recovery_workflow_topology (rec-2847 part (c) -- reconcile.yml red-recovery reachability)
# ---------------------------------------------------------------------------

_FRESH = "success() && steps.route.outputs.needs_fresh_plan == 'true'"
_LEGACY = "success() && steps.apply.outputs.stale == 'true'"
_APPLY_RUN = (
    "if printf '%s' \"$STDERR_CONTENT\" | grep -Eiq "
    "'saved plan is stale|plan file can no longer be applied|state was changed'; then\n"
    '  echo "::notice::STALE_PLAN_FRESH_REPLAN"\n'
    '  echo "stale=true" >> "$GITHUB_OUTPUT"\n'
    "fi"
)


def _recovery_topology_data(*, fresh_signal: str = _FRESH, route_step: bool = True) -> dict[str, Any]:
    """A minimal reconcile.yml shape the guard accepts, parameterised on the fallthrough gating."""
    steps: list[dict[str, Any]] = [
        {"id": "guard", "uses": "./.github/actions/deterministic-guard"},
        {"id": "apply", "if": "success() && steps.guard.outputs.routed != 'true'", "run": _APPLY_RUN},
    ]
    if route_step:
        steps.append(
            {
                "id": "route",
                "if": "success()",
                "env": {
                    "SAVED_PLAN_STALE": "${{ steps.apply.outputs.stale }}",
                    "SAVED_PLAN_ROUTED": "${{ steps.guard.outputs.routed }}",
                },
                "run": 'echo "needs_fresh_plan=true" >> "$GITHUB_OUTPUT"',
            }
        )
    steps += [
        {"id": "replan", "if": fresh_signal, "run": "terraform plan"},
        {"id": "guard_fresh", "if": fresh_signal, "uses": "./.github/actions/deterministic-guard"},
        {"id": "review_fresh", "if": f"{fresh_signal} && steps.guard_fresh.outputs.routed != 'true'"},
        {"id": "apply_fresh", "if": f"{fresh_signal} && steps.guard_fresh.outputs.routed != 'true'"},
        {
            "id": "upload_fresh_plan_sha256",
            "if": f"{fresh_signal} && steps.guard_fresh.outputs.routed == 'true'",
            "run": 'echo "sha256=..." >> "$GITHUB_OUTPUT"',
        },
        {
            "if": f"{fresh_signal} && steps.guard_fresh.outputs.routed == 'true'",
            "uses": "actions/upload-artifact@v4",
        },
    ]
    return {
        "jobs": {
            "apply-reconcile": {
                "outputs": {
                    "fresh_plan_pending": "${{ steps.upload_fresh_plan_sha256.outcome == 'success' }}",
                    "fresh_plan_sha256": "${{ steps.upload_fresh_plan_sha256.outputs.sha256 }}",
                },
                "steps": steps,
            },
            "gated-apply-reconcile": {
                "steps": [
                    {
                        "if": "needs.apply-reconcile.outputs.fresh_plan_pending == 'true'",
                        "uses": "actions/download-artifact@v4",
                    },
                    {
                        "if": "needs.apply-reconcile.outputs.fresh_plan_pending == 'true'",
                        "env": {"FRESH_PLAN_SHA256": "${{ needs.apply-reconcile.outputs.fresh_plan_sha256 }}"},
                        "run": "sha256sum plan.bin",
                    },
                    {
                        "id": "fetch_plan",
                        "if": "needs.apply-reconcile.outputs.fresh_plan_pending != 'true'",
                        "uses": "./.github/actions/fetch-saved-plan",
                    },
                ]
            },
        }
    }


class TestRecoveryWorkflowTopologyPassPath:
    def test_recovery_workflow_topology_passes_with_real_workflow_file(self) -> None:
        _check_recovery_workflow_topology()

    def test_recovery_workflow_topology_passes_with_valid_data(self) -> None:
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = _recovery_topology_data()
            _check_recovery_workflow_topology()


class TestRecoveryWorkflowTopologyFailPath:
    def test_recovery_workflow_topology_rejects_the_exact_pre_fix_shape(self) -> None:
        """LOAD-BEARING: the live rec-2847 defect -- fallthrough gated on the saved-plan apply's
        stale output with no `route` step -- must FAIL this guard. This is the "would it have
        caught the bug" proof, not a structural existence check.
        """
        data = _recovery_topology_data(fresh_signal=_LEGACY, route_step=False)
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = data
            with pytest.raises(AssertionError, match="has no `route` step"):
                _check_recovery_workflow_topology()

    def test_recovery_workflow_topology_rejects_legacy_stale_gating_with_route_present(self) -> None:
        data = _recovery_topology_data(fresh_signal=_LEGACY)
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = data
            with pytest.raises(AssertionError, match="still gated on"):
                _check_recovery_workflow_topology()

    def test_recovery_workflow_topology_rejects_route_step_reading_one_cause(self) -> None:
        data = _recovery_topology_data()
        route = data["jobs"]["apply-reconcile"]["steps"][2]
        del route["env"]["SAVED_PLAN_ROUTED"]
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = data
            with pytest.raises(AssertionError, match="does not read cause signal"):
                _check_recovery_workflow_topology()

    def test_recovery_workflow_topology_rejects_missing_fresh_plan_pending_output(self) -> None:
        data = _recovery_topology_data()
        del data["jobs"]["apply-reconcile"]["outputs"]["fresh_plan_pending"]
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = data
            with pytest.raises(AssertionError, match="fresh_plan_pending job output"):
                _check_recovery_workflow_topology()

    def test_recovery_workflow_topology_rejects_ungated_download_step(self) -> None:
        data = _recovery_topology_data()
        data["jobs"]["gated-apply-reconcile"]["steps"][0].pop("if")
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = data
            with pytest.raises(AssertionError, match="download step is not gated"):
                _check_recovery_workflow_topology()

    def test_recovery_workflow_topology_rejects_dropped_stale_signature_detection(self) -> None:
        data = _recovery_topology_data()
        data["jobs"]["apply-reconcile"]["steps"][1]["run"] = "terraform apply plan.bin"
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = data
            with pytest.raises(AssertionError, match="lost its stale-signature detection"):
                _check_recovery_workflow_topology()

    def test_recovery_workflow_topology_rejects_unmutually_exclusive_saved_plan_source(self) -> None:
        data = copy.deepcopy(_recovery_topology_data())
        data["jobs"]["gated-apply-reconcile"]["steps"][2]["if"] = "always()"
        with patch("scripts.verify_ci_workflow._load") as mock_load:
            mock_load.return_value = data
            with pytest.raises(AssertionError, match="mutually exclusive"):
                _check_recovery_workflow_topology()
