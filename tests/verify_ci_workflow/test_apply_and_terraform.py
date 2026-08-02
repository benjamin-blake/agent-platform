"""Tests for scripts/verify_ci_workflow.py -- apply-rca-fallback guard + terraform-apply-
concurrency guard concern (VERBATIM split from tests/test_verify_ci_workflow.py, rec-2709 Wave 12),
plus the recovery-workflow-topology guard (rec-2847 part (c)).
"""

from __future__ import annotations

import copy
import re
from typing import Any
from unittest.mock import patch

import pytest

from scripts.verify_ci_workflow import (
    _check_apply_rca_fallback,
    _check_recovery_workflow_topology,
    _check_terraform_apply_concurrency,
    _load,
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


# ---------------------------------------------------------------------------
# Decision 162 / PLAN-ci-rca-starved-surface: the strict review-outcome consumer's call-site
# pairing invariant (VP7), and the rec-2664 filing job's own shape (VP9) -- neither is covered by
# _check_recovery_workflow_topology, which enumerates four fresh-plan reachability invariants over
# apply-reconcile/gated-apply-reconcile only and would pass vacuously on both concerns here. These
# assertions load and parse the REAL workflow files directly (never a synthetic fixture) -- the
# call-site wiring and the new job are both load-bearing exactly as landed in this repo.
# ---------------------------------------------------------------------------


class TestReviewOutcomeCallsitePairing:
    """At every record-write call site, review-step-outcome and review-outcome are provably drawn
    from the SAME path selection, and the two gated call sites pass an explicitly empty pair.
    """

    def test_apply_sandbox_pairs_from_the_same_review_step(self) -> None:
        data = _load(".github/workflows/terraform-apply-sandbox.yml")
        step = next(s for s in data["jobs"]["apply-sandbox"]["steps"] if s.get("id") == "record_write")
        assert step["with"]["review-outcome"] == "${{ steps.review.outputs.outcome }}"
        assert step["with"]["review-step-outcome"] == "${{ steps.review.outcome }}"

    def test_sandbox_gated_apply_passes_explicit_empty_pair(self) -> None:
        data = _load(".github/workflows/terraform-apply-sandbox.yml")
        step = next(s for s in data["jobs"]["gated-apply"]["steps"] if s.get("id") == "record_write")
        assert step["with"].get("review-step-outcome", "") == ""
        assert "review-outcome" not in step["with"]

    def test_apply_reconcile_pairs_from_the_same_resolved_aggregator(self) -> None:
        data = _load(".github/workflows/reconcile.yml")
        step = next(s for s in data["jobs"]["apply-reconcile"]["steps"] if s.get("id") == "record_write")
        assert step["with"]["review-outcome"] == "${{ steps.resolved.outputs.review_outcome }}"
        assert step["with"]["review-step-outcome"] == "${{ steps.resolved.outputs.review_step_outcome }}"

    def test_gated_apply_reconcile_passes_explicit_empty_pair(self) -> None:
        data = _load(".github/workflows/reconcile.yml")
        step = next(s for s in data["jobs"]["gated-apply-reconcile"]["steps"] if s.get("id") == "record_write")
        assert step["with"].get("review-step-outcome", "") == ""
        assert "review-outcome" not in step["with"]

    def test_resolved_aggregator_pairs_review_step_outcome_from_the_same_branch(self) -> None:
        """The decision-scout catch: a naive `steps.review.outcome` reused across all three arms
        would pair the SAVED-PLAN review's step outcome with the FRESH-REPLAN path's value.
        """
        data = _load(".github/workflows/reconcile.yml")
        resolved = next(s for s in data["jobs"]["apply-reconcile"]["steps"] if s.get("id") == "resolved")
        body = resolved["run"]
        # The two needs_fresh=true arms pair with review_fresh; the else arm pairs with review.
        assert body.count("review_step_outcome=${{ steps.review_fresh.outcome }}") == 2
        assert body.count("review_step_outcome=${{ steps.review.outcome }}") == 1
        assert "review_outcome=${{ steps.review_fresh.outputs.outcome }}" in body
        assert "review_outcome=${{ steps.review.outputs.outcome }}" in body

    def test_apply_reconcile_declares_review_outcome_job_output(self) -> None:
        data = _load(".github/workflows/reconcile.yml")
        outputs = data["jobs"]["apply-reconcile"]["outputs"]
        assert outputs["review_outcome"] == "${{ steps.resolved.outputs.review_outcome }}"


class TestReconcileStarvedFilingJobShape:
    """rec-2664 / Decision 162: assert the new job's own shape directly -- it carries NO
    `terraform apply`, rides `always() && ... == 'starved'`, and assumes the branch role.
    """

    @pytest.fixture()
    def job(self) -> dict[str, Any]:
        data = _load(".github/workflows/reconcile.yml")
        return data["jobs"]["file-reconcile-starved-rec"]

    def test_job_exists(self, job: dict[str, Any]) -> None:
        assert job is not None

    def test_no_terraform_apply_in_any_step(self, job: dict[str, Any]) -> None:
        for step in job["steps"]:
            assert "terraform apply" not in (step.get("run") or "")

    def test_if_carries_always_and_the_starved_condition(self, job: dict[str, Any]) -> None:
        """The B3 trap the plan-critique gate caught: a bare `needs:` dependant is SKIPPED on
        exactly the failing episode this job exists to record (apply-reconcile concludes
        `failure` on STARVED, since review.sh exits 1).
        """
        condition = str(job["if"])
        assert "always()" in condition
        assert "needs.apply-reconcile.outputs.review_outcome == 'starved'" in condition

    def test_needs_apply_reconcile_explicitly(self, job: dict[str, Any]) -> None:
        assert "apply-reconcile" in job["needs"]

    def test_assumes_the_branch_role(self, job: dict[str, Any]) -> None:
        text = "\n".join(str(step) for step in job["steps"])
        assert "agent-platform-github-ci-branch" in text

    def test_files_a_rec_via_the_portal(self, job: dict[str, Any]) -> None:
        text = "\n".join(step.get("run") or "" for step in job["steps"])
        assert "file_rec" in text
        assert "reconcile_starved" in text

    @staticmethod
    def _extract_acceptance(job: dict[str, Any]) -> str:
        """Return the concatenated `acceptance` string literal the filing job passes to file_rec.

        The repeated group deliberately carries NO leading `\\s*` (the preceding `\\(\\s*` already
        consumes leading whitespace, and each iteration's trailing `\\s*` consumes the rest). A
        `(?:\\s*"[^"]*"\\s*)+` form -- whitespace matchable at BOTH ends of the repeat -- lets the
        gap between two literals be partitioned exponentially many ways, which CodeQL correctly
        flagged as polynomial/exponential backtracking on this PR (alerts 16/17): a non-matching
        input took 1.08s at 22 repetitions and quadrupled with every further pair.
        """
        text = "\n".join(step.get("run") or "" for step in job["steps"])
        match = re.search(r'"acceptance":\s*\(\s*((?:"[^"]*"\s*)+)\)', text)
        assert match, "could not locate the acceptance literal in the filing job's body"
        return "".join(re.findall(r'"([^"]*)"', match.group(1)))

    def test_acceptance_passes_the_live_portal_linter(self, job: dict[str, Any]) -> None:
        """LOAD-BEARING (code-review round 1, High #1). The portal registers acceptance_lint as a
        WRITE-TIME validator, so a prose acceptance value makes file_rec RAISE and this job file
        NOTHING on precisely the starved episode it exists to record -- a failure that would only
        ever surface during a live incident. Extract the literal the job actually passes and run
        it through the REAL linter, rather than grepping for the string 'file_rec' and inferring
        the write would succeed.
        """
        from scripts.executor.acceptance_lint import lint_acceptance_command

        acceptance = self._extract_acceptance(job)
        assert acceptance.strip(), "acceptance literal resolved empty"

        ok, error = lint_acceptance_command(acceptance)
        assert ok, f"acceptance value would be REJECTED by the portal at write time: {error}"

    def test_acceptance_is_not_prose(self, job: dict[str, Any]) -> None:
        """A defence-in-depth companion to the linter check: the linter only runs `bash -n`, so a
        prose sentence that happens to be bash-parseable would slip through it.
        """
        acceptance = self._extract_acceptance(job)
        assert not acceptance.startswith("Re-dispatch"), "acceptance regressed to the prose form"
        assert any(tok in acceptance for tok in ("aws ", "bin/venv-python", "grep ", "test ")), acceptance
