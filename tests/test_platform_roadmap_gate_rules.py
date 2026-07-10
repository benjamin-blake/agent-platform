"""Tests for scripts/platform_roadmap_gate_rules.py: tokenizer, evaluator, parser."""

from __future__ import annotations

import copy

import pytest

from scripts.platform_roadmap import (
    _GATE_HELPERS,
    GateRuleEvaluator,
    GateRuleParser,
    PlatformRoadmapState,
    RoadmapDocument,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_BASE_DOC: dict = {
    "document": {
        "id": "ROADMAP-TEST",
        "version": 1,
        "status": "draft",
        "filed_via": "pending_log_decision_lambda",
        "gate_helpers": [
            {"name": "tier_complete", "arity": 1},
            {"name": "all_in_tier_with_status", "arity": 2},
            {"name": "grace_period_elapsed", "arity": 2},
            {"name": "item_field_eq", "arity": 3},
        ],
    },
    "tier_items": [],
    "candidate_decisions": [],
    "cross_tier_gates": [],
}


def _doc(**overrides) -> dict:
    d = copy.deepcopy(_BASE_DOC)
    d.update(overrides)
    return d


def _item(item_id: str, tier: str = "T0", depends_on: list | None = None, status: str = "not_started") -> dict:
    return {
        "id": item_id,
        "tier": tier,
        "name": f"Test item {item_id}",
        "depends_on": depends_on or [],
        "files_in_scope": [],
        "exit_criteria": [],
        "effort": "S",
        "strategic": False,
        "status": status,
    }


def _state_from_doc(doc_dict: dict) -> PlatformRoadmapState:
    return PlatformRoadmapState(RoadmapDocument.model_validate(doc_dict))


# ---------------------------------------------------------------------------
# TestGateRuleGrammar
# ---------------------------------------------------------------------------


class TestGateRuleGrammar:
    def test_unknown_helper_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown"):
            GateRuleParser.validate("bogus_helper(T1.1)", _GATE_HELPERS)

    def test_arity_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="expected 1"):
            GateRuleParser.validate("tier_complete()", _GATE_HELPERS)

    def test_arity_mismatch_too_many_raises(self) -> None:
        with pytest.raises(ValueError, match="expected 1"):
            GateRuleParser.validate('tier_complete("T0", "T1")', _GATE_HELPERS)

    def test_tier_complete_passes(self) -> None:
        GateRuleParser.validate('tier_complete("T-1")', _GATE_HELPERS)

    def test_all_in_tier_with_status_passes(self) -> None:
        GateRuleParser.validate('all_in_tier_with_status("T2", "complete")', _GATE_HELPERS)

    def test_grace_period_elapsed_passes(self) -> None:
        GateRuleParser.validate("grace_period_elapsed(T4.2, 14)", _GATE_HELPERS)

    def test_item_field_eq_passes(self) -> None:
        GateRuleParser.validate('item_field_eq(T3.2, "latest_run.verdict", "PASS")', _GATE_HELPERS)

    def test_combined_rule_passes(self) -> None:
        rule = 'all_in_tier_with_status("T2", "complete") and grace_period_elapsed(T2.1, 30)'
        GateRuleParser.validate(rule, _GATE_HELPERS)

    def test_nested_parens_in_args_passes(self) -> None:
        # Exercises _find_close depth tracking and _count_args depth paths.
        # Semantically unusual but structurally valid: 2 args to grace_period_elapsed.
        GateRuleParser.validate('grace_period_elapsed(tier_complete("T0"), 14)', _GATE_HELPERS)

    def test_gate_rule_rejected_in_model(self) -> None:
        d = _doc(cross_tier_gates=[{"id": "G.X", "name": "test", "rule": "bogus_helper(T0.1)", "rationale": "test"}])
        with pytest.raises(Exception, match="Unknown"):
            RoadmapDocument.model_validate(d)

    def test_valid_gate_rule_in_model(self) -> None:
        d = _doc(cross_tier_gates=[{"id": "G.X", "name": "test", "rule": 'tier_complete("T0")', "rationale": "test"}])
        doc = RoadmapDocument.model_validate(d)
        assert doc.cross_tier_gates[0].id == "G.X"

    def test_cd_bad_gate_ref_raises(self) -> None:
        d = _doc(candidate_decisions=[{"id": "CD.X", "title": "T", "gates": ["T999.0"]}])
        with pytest.raises(Exception, match="does not resolve"):
            RoadmapDocument.model_validate(d)

    def test_cd_decision_required_before_bad_helper_raises(self) -> None:
        d = _doc(
            candidate_decisions=[
                {
                    "id": "CD.X",
                    "title": "T",
                    "decision_required_before": "bogus_helper(T1.1)",
                }
            ]
        )
        with pytest.raises(Exception, match="Unknown"):
            RoadmapDocument.model_validate(d)


# ---------------------------------------------------------------------------
# TestGateRuleEvaluator -- T-1.20: static helpers, Kleene tri-state, field resolution
# ---------------------------------------------------------------------------


class TestGateRuleEvaluator:
    def _all_complete_state(self) -> PlatformRoadmapState:
        doc = _doc(
            tier_items=[
                {**_item("T0.1", tier="T0"), "status": "complete"},
                {**_item("T0.2", tier="T0"), "status": "complete"},
            ]
        )
        return _state_from_doc(doc)

    def _partial_state(self) -> PlatformRoadmapState:
        doc = _doc(
            tier_items=[
                {**_item("T0.1", tier="T0"), "status": "complete"},
                {**_item("T0.2", tier="T0"), "status": "not_started"},
            ]
        )
        return _state_from_doc(doc)

    def test_tier_complete_pass(self) -> None:
        ev = GateRuleEvaluator(self._all_complete_state())
        verdict, reason = ev.evaluate('tier_complete("T0")')
        assert verdict == "pass"
        assert "True" in reason

    def test_tier_complete_fail(self) -> None:
        ev = GateRuleEvaluator(self._partial_state())
        verdict, _ = ev.evaluate('tier_complete("T0")')
        assert verdict == "fail"

    def test_all_in_tier_with_status_pass(self) -> None:
        ev = GateRuleEvaluator(self._all_complete_state())
        verdict, _ = ev.evaluate('all_in_tier_with_status("T0", "complete")')
        assert verdict == "pass"

    def test_all_in_tier_with_status_fail(self) -> None:
        ev = GateRuleEvaluator(self._partial_state())
        verdict, _ = ev.evaluate('all_in_tier_with_status("T0", "complete")')
        assert verdict == "fail"

    def test_grace_period_elapsed_pass(self) -> None:
        doc = _doc(tier_items=[{**_item("T0.1"), "status": "complete", "completed_at": "1970-01-01"}])
        ev = GateRuleEvaluator(_state_from_doc(doc))
        verdict, reason = ev.evaluate("grace_period_elapsed(T0.1, 30)")
        assert verdict == "pass"
        assert ">=" in reason

    def test_grace_period_elapsed_fail_item_incomplete(self) -> None:
        doc = _doc(tier_items=[_item("T0.1")])
        ev = GateRuleEvaluator(_state_from_doc(doc))
        verdict, reason = ev.evaluate("grace_period_elapsed(T0.1, 30)")
        assert verdict == "fail"
        assert "not complete" in reason

    def test_grace_period_elapsed_deferred_no_completed_at(self) -> None:
        doc = _doc(tier_items=[{**_item("T0.1"), "status": "complete"}])
        ev = GateRuleEvaluator(_state_from_doc(doc))
        verdict, reason = ev.evaluate("grace_period_elapsed(T0.1, 30)")
        assert verdict == "deferred"
        assert "completed_at" in reason

    def test_grace_period_elapsed_fail_too_recent(self) -> None:
        doc = _doc(tier_items=[{**_item("T0.1"), "status": "complete", "completed_at": "2026-06-01"}])
        ev = GateRuleEvaluator(_state_from_doc(doc))
        verdict, reason = ev.evaluate("grace_period_elapsed(T0.1, 99999)")
        assert verdict == "fail"
        assert ">=" in reason

    def test_kleene_fail_and_deferred_equals_fail(self) -> None:
        # tier_complete("T0") => fail (T0.2 not_started)
        # T0.2.latest_run.verdict => deferred (runtime path)
        # Kleene: fail AND deferred = fail
        ev = GateRuleEvaluator(self._partial_state())
        verdict, _ = ev.evaluate('tier_complete("T0") and T0.2.latest_run.verdict == "PASS"')
        assert verdict == "fail"

    def test_kleene_pass_or_deferred_equals_pass(self) -> None:
        # tier_complete("T0") => pass (all complete)
        # T0.1.latest_run.verdict => deferred (runtime path)
        # Kleene: pass OR deferred = pass
        ev = GateRuleEvaluator(self._all_complete_state())
        verdict, _ = ev.evaluate('tier_complete("T0") or T0.1.latest_run.verdict == "PASS"')
        assert verdict == "pass"

    def test_status_field_cmp_pass(self) -> None:
        doc = _doc(tier_items=[{**_item("T0.1"), "status": "complete"}])
        ev = GateRuleEvaluator(_state_from_doc(doc))
        verdict, reason = ev.evaluate('T0.1.status == "complete"')
        assert verdict == "pass"
        assert "complete" in reason

    def test_status_field_cmp_fail(self) -> None:
        doc = _doc(tier_items=[_item("T0.1")])
        ev = GateRuleEvaluator(_state_from_doc(doc))
        verdict, reason = ev.evaluate('T0.1.status == "complete"')
        assert verdict == "fail"
        assert "not_started" in reason

    def test_runtime_field_path_deferred(self) -> None:
        doc = _doc(tier_items=[_item("T0.1")])
        ev = GateRuleEvaluator(_state_from_doc(doc))
        verdict, _ = ev.evaluate('T0.1.latest_run.verdict == "PASS"')
        assert verdict == "deferred"

    def test_longest_prefix_collision_resolves_correct_item(self) -> None:
        # T9.1 (complete) and T9.1.2 (not_started) both present.
        # T9.1.status must resolve to T9.1 (not T9.1.2) via longest-known-id-prefix rule.
        # _sorted_ids = ["T9.1.2", "T9.1"] (length descending).
        # "T9.1.status" does NOT start with "T9.1.2." -> falls through to "T9.1." -> match.
        doc = _doc(
            tier_items=[
                {**_item("T9.1"), "status": "complete"},
                {**_item("T9.1.2"), "status": "not_started", "depends_on": ["T9.1"]},
            ]
        )
        ev = GateRuleEvaluator(_state_from_doc(doc))
        verdict, reason = ev.evaluate('T9.1.status == "complete"')
        assert verdict == "pass", f"expected pass (T9.1 is complete) but got {verdict!r}: {reason}"

    def test_not_inverts_pass_to_fail(self) -> None:
        ev = GateRuleEvaluator(self._all_complete_state())
        verdict, _ = ev.evaluate('not tier_complete("T0")')
        assert verdict == "fail"

    def test_not_inverts_fail_to_pass(self) -> None:
        ev = GateRuleEvaluator(self._partial_state())
        verdict, _ = ev.evaluate('not tier_complete("T0")')
        assert verdict == "pass"

    def test_item_field_eq_always_deferred(self) -> None:
        doc = _doc(tier_items=[_item("T0.1")])
        ev = GateRuleEvaluator(_state_from_doc(doc))
        verdict, reason = ev.evaluate('item_field_eq(T0.1, "latest_run.verdict", "PASS")')
        assert verdict == "deferred"
        assert "runtime" in reason.lower() or "deferred" in reason.lower()

    def test_unknown_item_in_field_path_deferred(self) -> None:
        doc = _doc(tier_items=[_item("T0.1")])
        ev = GateRuleEvaluator(_state_from_doc(doc))
        verdict, _ = ev.evaluate('T999.1.status == "complete"')
        assert verdict == "deferred"
