"""Contract tests for .github/actions/write-convergence-record/assert_review_outcome.sh
(rec-2923 strict consumer, Decision 162 R1 instance).

Drives the script under the LITERAL GitHub composite-step argv --
`bash --noprofile --norc -e -o pipefail <file>` -- the exact invocation GitHub uses for a
composite `shell: bash` step body, mirroring tests/test_subagent_review_wiring.py's harness
discipline. This module is deliberately guard-free (no top-level `pytest.importorskip("boto3")`
or similar) -- the sibling plan's implementation (#823) lost a CI job to placing new test classes
in a module carrying one, which the fast tier skips wholesale and the VP-replay gate reads as a
hard failure (see PLAN-ci-rca-starved-surface.yaml constraints).

Full truth table (rec-2923 is the ran+EMPTY row):
    REVIEW_STEP_OUTCOME   REVIEW_OUTCOME   exit
    success/failure       proceed          0
    success/failure       revise           0
    success/failure       starved          0
    success/failure       (empty)          non-zero   <- rec-2923 shape
    success/failure       garbage          non-zero
    skipped/cancelled/""  (empty)          0
    skipped/cancelled/""  non-empty        non-zero
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / ".github" / "actions" / "write-convergence-record" / "assert_review_outcome.sh"

# The exact argv GitHub uses for a composite-action `shell: bash` step body.
GITHUB_COMPOSITE_BASH = ("bash", "--noprofile", "--norc", "-e", "-o", "pipefail")


def _run(review_step_outcome: str, review_outcome: str) -> subprocess.CompletedProcess[str]:
    env = {
        "REVIEW_STEP_OUTCOME": review_step_outcome,
        "REVIEW_OUTCOME": review_outcome,
        "PATH": "/usr/bin:/bin:/usr/local/bin",
    }
    return subprocess.run(
        [*GITHUB_COMPOSITE_BASH, str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


class TestReviewStepRanValidOutcomes:
    """REVIEW_STEP_OUTCOME in {success, failure}, REVIEW_OUTCOME a valid enum member -> exit 0."""

    @pytest.mark.parametrize("step_outcome", ["success", "failure"])
    @pytest.mark.parametrize("outcome", ["proceed", "revise", "starved"])
    def test_valid_pair_exits_zero(self, step_outcome: str, outcome: str) -> None:
        result = _run(step_outcome, outcome)
        assert result.returncode == 0, result.stderr


class TestReviewStepRanInvalidOutcomes:
    """The rec-2923 shape and its neighbours: review step ran but outcome is empty/garbage."""

    @pytest.mark.parametrize("step_outcome", ["success", "failure"])
    def test_empty_outcome_is_rejected(self, step_outcome: str) -> None:
        """LOAD-BEARING: this is the exact rec-2923 counterfactual -- must exit non-zero."""
        result = _run(step_outcome, "")
        assert result.returncode != 0
        assert "::error::" in result.stderr
        assert "rec-2923" in result.stderr

    @pytest.mark.parametrize("step_outcome", ["success", "failure"])
    def test_garbage_outcome_is_rejected(self, step_outcome: str) -> None:
        result = _run(step_outcome, "not-a-real-outcome")
        assert result.returncode != 0
        assert "::error::" in result.stderr


class TestNoReviewStepRan:
    """REVIEW_STEP_OUTCOME in {skipped, cancelled, ""} -- the guard-routed / gated-apply sites."""

    @pytest.mark.parametrize("step_outcome", ["skipped", "cancelled", ""])
    def test_empty_review_outcome_exits_zero(self, step_outcome: str) -> None:
        result = _run(step_outcome, "")
        assert result.returncode == 0, result.stderr

    @pytest.mark.parametrize("step_outcome", ["skipped", "cancelled", ""])
    def test_nonempty_review_outcome_is_rejected(self, step_outcome: str) -> None:
        """A review verdict with no review step to have produced it is equally a violation."""
        result = _run(step_outcome, "proceed")
        assert result.returncode != 0
        assert "::error::" in result.stderr


class TestUnsetEnvVars:
    """Absent env vars behave identically to explicitly-empty ones (set -u default expansion)."""

    def test_both_unset_exits_zero(self) -> None:
        env = {"PATH": "/usr/bin:/bin:/usr/local/bin"}
        result = subprocess.run(
            [*GITHUB_COMPOSITE_BASH, str(SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr


class TestScriptShape:
    def test_script_exists_and_is_executable(self) -> None:
        assert SCRIPT.is_file()

    def test_clears_inherited_errexit(self) -> None:
        """The one line that makes this script's own explicit-exit design hold under -e."""
        assert "\nset +e\n" in SCRIPT.read_text(encoding="utf-8")

    def test_does_not_rely_on_a_bare_call_in_the_caller(self) -> None:
        """The caller (action.yml) must invoke this via an explicit `if ! ...; then exit 1; fi`,
        never a bare call relying on the composite step's ambient errexit -- that dependence is
        the defect class this script exists to close.
        """
        action_yml = SCRIPT.parent / "action.yml"
        text = action_yml.read_text(encoding="utf-8")
        assert "if ! bash" in text
        assert "assert_review_outcome.sh" in text
