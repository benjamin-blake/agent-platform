"""Tests for scripts/ci/reconcile_reachability.py -- AND the harness's own ground truth.

PROVENANCE OF THE PRE-FIX FIXTURE. _PRE_FIX_STEPS below is a frozen VERBATIM extract of
.github/workflows/reconcile.yml's apply-reconcile step list at merge-base
cdb043a73113049480b066f902144798b7398a39 -- captured with
`git show cdb043a73113049480b066f902144798b7398a39:.github/workflows/reconcile.yml` and read out of
the parsed YAML, never hand-retyped (a hand-copied fixture proves only that the author's memory
agrees with itself). Only `id`, `name` and `if:` are retained -- the evaluator reads nothing else.
The range is `guard` .. the upload-artifact step, one step wider than `apply` .. upload-artifact,
because the `guard` step is where the BLOCK signal ORIGINATES: a fixture starting at `apply` would
never set steps.guard.outputs.routed and would silently invert the ground truth.

BOTH DIRECTIONS ARE ASSERTED, and that is the point. The pre-fix direction (guard=BLOCK -> `replan`
UNREACHABLE) is what live run 30264239445 empirically did; the post-fix direction (same context,
real on-disk file -> `replan` REACHABLE) is the claim under test. A harness that only proved the
post-fix direction would be a self-confirming reimplementation of the very `if:` strings it reads.
IF THE PRE-FIX ASSERTION EVER FAILS, THE HARNESS IS WRONG -- fix the evaluator, never the
expectation.
"""

from __future__ import annotations

from typing import Any

import pytest

from scripts.ci.reconcile_reachability import (
    UnsupportedExpressionError,
    _State,
    evaluate,
    evaluate_condition,
    load_steps,
    main,
    parse_context,
)

REAL_WORKFLOW = ".github/workflows/reconcile.yml"

PRE_FIX_MERGE_BASE_SHA = "cdb043a73113049480b066f902144798b7398a39"  # pragma: allowlist secret -- git sha, not a value

_PRE_FIX_STEPS: list[dict[str, Any]] = [
    {
        "id": "guard",
        "name": "Deterministic apply guard (fail-closed) -- saved plan",
        "if": "success()",
    },
    {
        "id": "review",
        "name": "Subagent plan review (digest-fed, JSON-classified) -- saved plan",
        "if": "success() && steps.guard.outputs.routed != 'true'",
    },
    {
        "id": "apply",
        "name": "Terraform apply (same plan file the guard inspected) -- saved plan",
        "if": "success() && steps.guard.outputs.routed != 'true'",
    },
    {
        "id": "replan",
        "name": "Fresh re-plan (STALE_PLAN_FRESH_REPLAN fallthrough)",
        "if": "success() && steps.apply.outputs.stale == 'true'",
    },
    {
        "id": "guard_fresh",
        "name": "Deterministic apply guard (fail-closed) -- fresh re-plan",
        "if": "success() && steps.apply.outputs.stale == 'true'",
    },
    {
        "id": "review_fresh",
        "name": "Subagent plan review (digest-fed, JSON-classified) -- fresh re-plan",
        "if": "success() && steps.apply.outputs.stale == 'true' && steps.guard_fresh.outputs.routed != 'true'",
    },
    {
        "id": "apply_fresh",
        "name": "Terraform apply (fresh re-plan, guard-PASS)",
        "if": "success() && steps.apply.outputs.stale == 'true' && steps.guard_fresh.outputs.routed != 'true'",
    },
    {
        "id": "upload_fresh_plan_sha256",
        "name": "Emit fresh plan.bin sha256 (RECONCILE_FRESH_PLAN_ARTIFACT sha256 job-output EMIT)",
        "if": "success() && steps.apply.outputs.stale == 'true' && steps.guard_fresh.outputs.routed == 'true'",
    },
    {
        "id": None,
        "name": "Upload fresh plan.bin as a run-scoped artifact (RECONCILE_FRESH_PLAN_ARTIFACT)",
        "if": "success() && steps.apply.outputs.stale == 'true' && steps.guard_fresh.outputs.routed == 'true'",
    },
]

ALL_CONTEXTS = (
    {"guard": "PASS", "apply": "success"},
    {"guard": "PASS", "apply": "stale"},
    {"guard": "PASS", "apply": "failure"},
    {"guard": "BLOCK", "guard_fresh": "BLOCK"},
    {"guard": "BLOCK", "guard_fresh": "PASS"},
)


def _reachable(steps: list[dict[str, Any]], context: dict[str, str], key: str) -> bool:
    matches = [result for result in evaluate(steps, context) if result.key == key]
    assert matches, f"no step {key!r} in the evaluated step list"
    return matches[0].reachable


# ---------------------------------------------------------------------------
# (i) token-subset unit tests
# ---------------------------------------------------------------------------


class TestTokenSubset:
    def test_success_is_false_once_a_prior_step_failed(self) -> None:
        state = _State(failed=True)
        assert evaluate_condition("success()", state) is False
        assert evaluate_condition("always()", state) is True

    def test_missing_if_is_implicit_success(self) -> None:
        assert evaluate_condition(None, _State()) is True
        assert evaluate_condition(None, _State(failed=True)) is False

    def test_unset_output_reads_as_empty_string_not_the_literal_false(self) -> None:
        """A guard PASS leaves steps.guard.outputs.routed EMPTY, never 'false' -- load-bearing."""
        state = _State()
        assert evaluate_condition("steps.guard.outputs.routed != 'true'", state) is True
        assert evaluate_condition("steps.guard.outputs.routed == 'false'", state) is False
        state.outputs["steps.guard.outputs.routed"] = "false"
        assert evaluate_condition("steps.guard.outputs.routed == 'false'", state) is True

    def test_and_chain_requires_every_term(self) -> None:
        state = _State(outputs={"steps.route.outputs.needs_fresh_plan": "true"})
        expression = (
            "success() && steps.route.outputs.needs_fresh_plan == 'true' && steps.guard_fresh.outputs.routed != 'true'"
        )
        assert evaluate_condition(expression, state) is True
        state.outputs["steps.guard_fresh.outputs.routed"] = "true"
        assert evaluate_condition(expression, state) is False

    def test_outcome_lookup_is_supported(self) -> None:
        state = _State(outcomes={"apply": "skipped"})
        assert evaluate_condition("steps.apply.outcome == 'skipped'", state) is True

    def test_template_wrapper_is_unwrapped(self) -> None:
        assert evaluate_condition("${{ success() }}", _State()) is True

    def test_unknown_token_raises_rather_than_guessing(self) -> None:
        with pytest.raises(UnsupportedExpressionError, match="unsupported construct"):
            evaluate_condition("success() && github.event_name == 'push'", _State())

    def test_bare_lookup_in_boolean_position_raises(self) -> None:
        with pytest.raises(UnsupportedExpressionError, match="unsupported term"):
            evaluate_condition("success() && steps.guard.outputs.routed", _State())

    def test_empty_condition_raises(self) -> None:
        with pytest.raises(UnsupportedExpressionError, match="empty condition"):
            evaluate_condition("   ", _State())

    def test_unknown_context_key_and_value_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown context key"):
            evaluate(_PRE_FIX_STEPS, {"nonsense": "PASS"})
        with pytest.raises(ValueError, match="is not one of"):
            evaluate(_PRE_FIX_STEPS, {"guard": "MAYBE"})

    def test_parse_context_forms(self) -> None:
        assert parse_context("guard=BLOCK, guard_fresh=PASS") == {"guard": "BLOCK", "guard_fresh": "PASS"}
        assert parse_context("") == {}
        with pytest.raises(ValueError, match="is not k=v"):
            parse_context("guard")

    def test_load_steps_rejects_an_unknown_job(self) -> None:
        with pytest.raises(ValueError, match="has no 'nope' job"):
            load_steps(REAL_WORKFLOW, "nope")


# ---------------------------------------------------------------------------
# (ii)/(iii) ground truth -- BOTH directions
# ---------------------------------------------------------------------------


class TestGroundTruthBothDirections:
    def test_pre_fix_replan_is_unreachable_on_a_saved_plan_guard_block(self) -> None:
        """THE PRE-FIX DIRECTION. Live run 30264239445 skipped `replan` on a guard-BLOCK; the
        harness must reproduce that, or its post-fix result is not evidence.
        """
        assert _reachable(_PRE_FIX_STEPS, {"guard": "BLOCK"}, "replan") is False
        assert _reachable(_PRE_FIX_STEPS, {"guard": "BLOCK"}, "apply") is False
        for key in ("guard_fresh", "review_fresh", "apply_fresh", "upload_fresh_plan_sha256"):
            assert _reachable(_PRE_FIX_STEPS, {"guard": "BLOCK"}, key) is False

    def test_pre_fix_stale_route_was_reachable_on_a_guard_pass(self) -> None:
        """The pre-fix file was not wholly broken -- the DEP-10 STALE route worked. This is what
        makes the defect a MISSING CAUSE rather than a dead fallthrough.
        """
        assert _reachable(_PRE_FIX_STEPS, {"guard": "PASS", "apply": "stale"}, "replan") is True

    def test_post_fix_replan_is_reachable_on_a_saved_plan_guard_block(self) -> None:
        """THE POST-FIX DIRECTION, against the REAL on-disk workflow under the same context."""
        steps = load_steps(REAL_WORKFLOW)
        assert _reachable(steps, {"guard": "BLOCK", "guard_fresh": "BLOCK"}, "replan") is True
        assert _reachable(steps, {"guard": "BLOCK", "guard_fresh": "PASS"}, "replan") is True

    def test_post_fix_preserves_the_stale_route_and_the_guard_pass_route(self) -> None:
        steps = load_steps(REAL_WORKFLOW)
        assert _reachable(steps, {"guard": "PASS", "apply": "stale"}, "replan") is True
        assert _reachable(steps, {"guard": "PASS", "apply": "success"}, "replan") is False
        assert _reachable(steps, {"guard": "PASS", "apply": "success"}, "apply") is True

    def test_post_fix_terminal_routes_out_of_a_saved_plan_guard_block(self) -> None:
        """Decision 158's complete terminal set, asserted as reachability."""
        steps = load_steps(REAL_WORKFLOW)
        gated = {"guard": "BLOCK", "guard_fresh": "BLOCK"}
        auto = {"guard": "BLOCK", "guard_fresh": "PASS"}
        # (i) fresh guard-PASS -> subagent review then auto-apply in apply-reconcile.
        assert _reachable(steps, auto, "review_fresh") is True
        assert _reachable(steps, auto, "apply_fresh") is True
        assert _reachable(steps, auto, "upload_fresh_plan_sha256") is False
        # (ii) fresh guard-BLOCK -> artifact hand-off to the Environment-gated job.
        assert _reachable(steps, gated, "upload_fresh_plan_sha256") is True
        assert _reachable(steps, gated, "apply_fresh") is False

    def test_replan_failure_short_circuits_to_the_red_latch(self) -> None:
        """Route (iii): a pre-`route` apply failure short-circuits every downstream step on
        success(), leaving only the always-run record write (Decision 154 point 5(i)).
        """
        steps = load_steps(REAL_WORKFLOW)
        context = {"guard": "PASS", "apply": "failure"}
        assert _reachable(steps, context, "route") is False
        assert _reachable(steps, context, "replan") is False
        assert _reachable(steps, context, "record_write") is True


# ---------------------------------------------------------------------------
# (iv) every declared context evaluates without an unparsed token
# ---------------------------------------------------------------------------


class TestAllContextsEvaluate:
    @pytest.mark.parametrize("context", ALL_CONTEXTS)
    def test_real_workflow_evaluates_cleanly(self, context: dict[str, str]) -> None:
        results = evaluate(load_steps(REAL_WORKFLOW), context)
        assert results
        assert all(result.key != "<unnamed>" for result in results)

    @pytest.mark.parametrize("context", ALL_CONTEXTS)
    def test_pre_fix_extract_evaluates_cleanly(self, context: dict[str, str]) -> None:
        assert evaluate(_PRE_FIX_STEPS, context)


class TestCli:
    def test_cli_reports_a_single_step(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = main([REAL_WORKFLOW, "--context", "guard=BLOCK,guard_fresh=BLOCK", "--step", "replan"])
        assert code == 0
        assert capsys.readouterr().out.strip() == "REACHABLE replan"

    def test_cli_reports_every_step_by_default(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main([REAL_WORKFLOW, "--context", "guard=PASS,apply=success"]) == 0
        out = capsys.readouterr().out
        assert "REACHABLE route" in out
        assert "UNREACHABLE replan" in out

    def test_cli_exits_non_zero_on_a_bad_context(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main([REAL_WORKFLOW, "--context", "guard=MAYBE"]) == 1
        assert "ERROR" in capsys.readouterr().err

    def test_cli_exits_non_zero_on_an_unknown_step(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main([REAL_WORKFLOW, "--step", "nope"]) == 1
        assert "no step 'nope'" in capsys.readouterr().err

    def test_str_renders_the_reachability_verdict(self) -> None:
        results = evaluate(_PRE_FIX_STEPS, {"guard": "BLOCK"})
        assert str(results[0]) == "REACHABLE guard"
