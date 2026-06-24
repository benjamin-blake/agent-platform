"""Tests for scripts/platform_roadmap.py covering all T-1.5 exit criteria."""

from __future__ import annotations

import copy
import tempfile
from pathlib import Path

import pytest
import yaml

from scripts.platform_roadmap import (
    _GATE_HELPERS,
    ExitCriterion,
    GateRuleEvaluator,
    GateRuleParser,
    PlatformRoadmapState,
    RoadmapDocument,
    TierItem,
    compute_followon_state,
    compute_state_dict,
    load,
)
from scripts.session_preflight import _slim_roadmap_state

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


# ---------------------------------------------------------------------------
# TestLoad
# ---------------------------------------------------------------------------


class TestLoad:
    def test_loads_live_yaml(self) -> None:
        roadmap = Path(__file__).parent.parent / "docs" / "ROADMAP-PLATFORM.yaml"
        doc = load(roadmap)
        assert len(doc.tier_items) >= 30
        assert len(doc.candidate_decisions) >= 20

    def test_missing_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load("/nonexistent/path/ROADMAP.yaml")

    def test_invalid_yaml_raises(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False, encoding="utf-8") as f:
            f.write(":: not valid yaml: [[[")
            tmp = f.name
        try:
            with pytest.raises((yaml.YAMLError, Exception)):
                load(tmp)
        finally:
            Path(tmp).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# TestStructuralValidation
# ---------------------------------------------------------------------------


class TestStructuralValidation:
    def test_tier_items_wrong_type_raises(self) -> None:
        with pytest.raises(Exception):
            RoadmapDocument.model_validate(_doc(tier_items="not-a-list"))

    def test_missing_document_raises(self) -> None:
        with pytest.raises(Exception):
            RoadmapDocument.model_validate({"tier_items": []})

    def test_valid_minimal_doc_passes(self) -> None:
        doc = RoadmapDocument.model_validate(_BASE_DOC)
        assert doc.document.id == "ROADMAP-TEST"

    def test_unsupported_version_raises(self) -> None:
        d = _doc()
        d["document"]["version"] = 99
        with pytest.raises(Exception, match="Unsupported"):
            RoadmapDocument.model_validate(d)


# ---------------------------------------------------------------------------
# TestIdUniqueness
# ---------------------------------------------------------------------------


class TestIdUniqueness:
    def test_duplicate_id_raises(self) -> None:
        d = _doc(tier_items=[_item("T0.1"), _item("T0.1")])
        with pytest.raises(Exception, match="[Dd]uplicate"):
            RoadmapDocument.model_validate(d)

    def test_unique_ids_pass(self) -> None:
        d = _doc(tier_items=[_item("T0.1"), _item("T0.2")])
        doc = RoadmapDocument.model_validate(d)
        assert len(doc.tier_items) == 2


# ---------------------------------------------------------------------------
# TestDanglingDependsOn
# ---------------------------------------------------------------------------


class TestDanglingDependsOn:
    def test_nonexistent_dep_raises(self) -> None:
        d = _doc(tier_items=[_item("T0.1", depends_on=["T999.0"])])
        with pytest.raises(Exception, match="does not resolve"):
            RoadmapDocument.model_validate(d)

    def test_valid_dep_passes(self) -> None:
        d = _doc(tier_items=[_item("T0.1"), _item("T0.2", depends_on=["T0.1"])])
        doc = RoadmapDocument.model_validate(d)
        assert doc.tier_items[1].depends_on == ["T0.1"]

    def test_tier_shortcut_dep_passes(self) -> None:
        d = _doc(tier_items=[_item("T0.1", tier="T0"), _item("T1.1", tier="T1", depends_on=["T0"])])
        doc = RoadmapDocument.model_validate(d)
        assert "T0" in doc.tier_items[1].depends_on


# ---------------------------------------------------------------------------
# TestCycleDetection
# ---------------------------------------------------------------------------


class TestCycleDetection:
    def test_direct_cycle_raises(self) -> None:
        d = _doc(
            tier_items=[
                _item("T0.1", depends_on=["T0.2"]),
                _item("T0.2", depends_on=["T0.1"]),
            ]
        )
        with pytest.raises(Exception, match="[Cc]ycle"):
            RoadmapDocument.model_validate(d)

    def test_three_node_cycle_raises(self) -> None:
        d = _doc(
            tier_items=[
                _item("T0.1", depends_on=["T0.3"]),
                _item("T0.2", depends_on=["T0.1"]),
                _item("T0.3", depends_on=["T0.2"]),
            ]
        )
        with pytest.raises(Exception, match="[Cc]ycle"):
            RoadmapDocument.model_validate(d)

    def test_linear_chain_passes(self) -> None:
        d = _doc(
            tier_items=[
                _item("T0.1"),
                _item("T0.2", depends_on=["T0.1"]),
                _item("T0.3", depends_on=["T0.2"]),
            ]
        )
        doc = RoadmapDocument.model_validate(d)
        assert len(doc.tier_items) == 3

    def test_tier_shortcut_cycle_raises(self) -> None:
        # T0.1 in T0 depends on tier T1; T1.1 in T1 depends on tier T0 -> cycle
        d = _doc(
            tier_items=[
                _item("T0.1", tier="T0", depends_on=["T1"]),
                _item("T1.1", tier="T1", depends_on=["T0"]),
            ]
        )
        with pytest.raises(Exception, match="[Cc]ycle"):
            RoadmapDocument.model_validate(d)


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
# TestFiledViaUnion
# ---------------------------------------------------------------------------


class TestFiledViaUnion:
    def test_pending_log_decision_lambda_accepted(self) -> None:
        d = _doc()
        d["document"]["filed_via"] = "pending_log_decision_lambda"
        doc = RoadmapDocument.model_validate(d)
        assert doc.document.filed_via == "pending_log_decision_lambda"

    def test_ops_decisions_ref_accepted(self) -> None:
        d = _doc()
        d["document"]["filed_via"] = "ops_decisions:dec-042"
        doc = RoadmapDocument.model_validate(d)
        assert doc.document.filed_via == "ops_decisions:dec-042"

    def test_arbitrary_string_raises(self) -> None:
        d = _doc()
        d["document"]["filed_via"] = "something_else"
        with pytest.raises(Exception, match="Invalid filed_via"):
            RoadmapDocument.model_validate(d)

    def test_ops_decisions_without_number_raises(self) -> None:
        d = _doc()
        d["document"]["filed_via"] = "ops_decisions:dec-abc"
        with pytest.raises(Exception, match="Invalid filed_via"):
            RoadmapDocument.model_validate(d)


# ---------------------------------------------------------------------------
# TestPlatformRoadmapState
# ---------------------------------------------------------------------------


class TestPlatformRoadmapState:
    def _make_doc(self, items: list[dict]) -> RoadmapDocument:
        return RoadmapDocument.model_validate(_doc(tier_items=items))

    def test_eligible_items_no_deps(self) -> None:
        doc = self._make_doc([_item("T0.1"), _item("T0.2")])
        state = PlatformRoadmapState(doc)
        eligible_ids = {i.id for i in state.eligible_items()}
        assert eligible_ids == {"T0.1", "T0.2"}

    def test_eligible_items_with_complete_dep(self) -> None:
        doc = self._make_doc(
            [
                _item("T0.1", status="complete"),
                _item("T0.2", depends_on=["T0.1"]),
            ]
        )
        state = PlatformRoadmapState(doc)
        eligible_ids = {i.id for i in state.eligible_items()}
        assert eligible_ids == {"T0.2"}

    def test_compute_blocked_with_incomplete_dep(self) -> None:
        doc = self._make_doc(
            [
                _item("T0.1"),
                _item("T0.2", depends_on=["T0.1"]),
            ]
        )
        state = PlatformRoadmapState(doc)
        blocked_ids = {i.id for i in state.compute_blocked()}
        assert blocked_ids == {"T0.2"}

    def test_tier_complete_all_done(self) -> None:
        doc = self._make_doc(
            [
                _item("T0.1", tier="T0", status="complete"),
                _item("T0.2", tier="T0", status="complete"),
            ]
        )
        state = PlatformRoadmapState(doc)
        assert state.tier_complete("T0") is True

    def test_tier_complete_with_incomplete(self) -> None:
        doc = self._make_doc(
            [
                _item("T0.1", tier="T0", status="complete"),
                _item("T0.2", tier="T0", status="not_started"),
            ]
        )
        state = PlatformRoadmapState(doc)
        assert state.tier_complete("T0") is False

    def test_tier_complete_reserved_excluded(self) -> None:
        doc = self._make_doc(
            [
                _item("T0.1", tier="T0", status="complete"),
                {**_item("T0.2", tier="T0"), "status": "reserved"},
            ]
        )
        state = PlatformRoadmapState(doc)
        assert state.tier_complete("T0") is True

    def test_tier_shortcut_eligible_resolution(self) -> None:
        doc = self._make_doc(
            [
                _item("T0.1", tier="T0", status="complete"),
                _item("T1.1", tier="T1", depends_on=["T0"]),
            ]
        )
        state = PlatformRoadmapState(doc)
        eligible_ids = {i.id for i in state.eligible_items()}
        assert "T1.1" in eligible_ids

    def test_resolve_depends_on(self) -> None:
        doc = self._make_doc(
            [
                _item("T0.1"),
                _item("T0.2", depends_on=["T0.1"]),
            ]
        )
        state = PlatformRoadmapState(doc)
        deps = state.resolve_depends_on("T0.2")
        assert len(deps) == 1
        assert deps[0].id == "T0.1"

    def test_resolve_depends_on_tier_shortcut(self) -> None:
        doc = self._make_doc(
            [
                _item("T0.1", tier="T0"),
                _item("T0.2", tier="T0"),
                _item("T1.1", tier="T1", depends_on=["T0"]),
            ]
        )
        state = PlatformRoadmapState(doc)
        deps = state.resolve_depends_on("T1.1")
        dep_ids = {d.id for d in deps}
        assert dep_ids == {"T0.1", "T0.2"}

    def test_resolve_depends_on_nonexistent_returns_empty(self) -> None:
        doc = self._make_doc([_item("T0.1")])
        state = PlatformRoadmapState(doc)
        assert state.resolve_depends_on("T999.0") == []


# ---------------------------------------------------------------------------
# TestCD25SchemaAmendments -- T-1.12 amendments per PLAN-cd25-platform-gap-sequencing
# ---------------------------------------------------------------------------


class TestCD25SchemaAmendments:
    def test_bootstrap_completion_exempt_accepts_true(self) -> None:
        item = {**_item("T-1.11"), "bootstrap_completion_exempt": True}
        doc = RoadmapDocument.model_validate(_doc(tier_items=[item]))
        assert doc.tier_items[0].bootstrap_completion_exempt is True

    def test_bootstrap_completion_exempt_defaults_false(self) -> None:
        doc = RoadmapDocument.model_validate(_doc(tier_items=[_item("T0.1")]))
        assert doc.tier_items[0].bootstrap_completion_exempt is False

    def test_tier_item_decision_required_before_accepts_list(self) -> None:
        item = {**_item("T1.12"), "decision_required_before": ["CD.16 ratifies"]}
        doc = RoadmapDocument.model_validate(_doc(tier_items=[item]))
        assert doc.tier_items[0].decision_required_before == ["CD.16 ratifies"]

    def test_tier_item_decision_required_before_accepts_none(self) -> None:
        doc = RoadmapDocument.model_validate(_doc(tier_items=[_item("T0.1")]))
        assert doc.tier_items[0].decision_required_before is None

    def test_cd_decision_required_before_accepts_list(self) -> None:
        cd = {"id": "CD.X", "title": "T", "decision_required_before": ["T0.13 may start"]}
        doc = RoadmapDocument.model_validate(_doc(candidate_decisions=[cd]))
        assert doc.candidate_decisions[0].decision_required_before == ["T0.13 may start"]

    def test_cd_decision_required_before_accepts_string_still(self) -> None:
        cd = {"id": "CD.X", "title": "T", "decision_required_before": "prose entry"}
        doc = RoadmapDocument.model_validate(_doc(candidate_decisions=[cd]))
        assert doc.candidate_decisions[0].decision_required_before == "prose entry"

    def test_cd_decision_required_before_list_with_bad_helper_raises(self) -> None:
        cd = {"id": "CD.X", "title": "T", "decision_required_before": ["bogus_helper(T1.1)"]}
        with pytest.raises(Exception, match="Unknown"):
            RoadmapDocument.model_validate(_doc(candidate_decisions=[cd]))

    def test_bootstrap_allowance_accepts_true(self) -> None:
        cd = {"id": "CD.25", "title": "T", "bootstrap_allowance": True}
        doc = RoadmapDocument.model_validate(_doc(candidate_decisions=[cd]))
        assert doc.candidate_decisions[0].bootstrap_allowance is True

    def test_bootstrap_allowance_defaults_false(self) -> None:
        cd = {"id": "CD.X", "title": "T"}
        doc = RoadmapDocument.model_validate(_doc(candidate_decisions=[cd]))
        assert doc.candidate_decisions[0].bootstrap_allowance is False

    def test_decomposition_hints_dict_accepted(self) -> None:
        item = {**_item("T-1.12"), "decomposition_hints": {"split_by": "subsystem", "atomic_plans": ["a", "b"]}}
        doc = RoadmapDocument.model_validate(_doc(tier_items=[item]))
        assert doc.tier_items[0].decomposition_hints == {"split_by": "subsystem", "atomic_plans": ["a", "b"]}

    def test_decomposition_hints_list_rejected(self) -> None:
        item = {**_item("T4.1"), "decomposition_hints": ["plan_a", "plan_b"]}
        with pytest.raises(Exception):
            RoadmapDocument.model_validate(_doc(tier_items=[item]))

    def test_tier_item_extra_forbid_rejects_bogus_field(self) -> None:
        item = {**_item("T0.1"), "bogus_field": 1}
        with pytest.raises(Exception, match="bogus_field|Extra inputs"):
            RoadmapDocument.model_validate(_doc(tier_items=[item]))

    def test_cd_extra_forbid_rejects_bogus_field(self) -> None:
        cd = {"id": "CD.X", "title": "T", "bogus_field": 1}
        with pytest.raises(Exception, match="bogus_field|Extra inputs"):
            RoadmapDocument.model_validate(_doc(candidate_decisions=[cd]))

    def test_other_classes_still_extra_ignore(self) -> None:
        # NorthStar uses extra="ignore"; unknown fields are dropped without error.
        d = _doc(north_star={"principles": [], "bogus_field": "ignored"})
        doc = RoadmapDocument.model_validate(d)
        assert doc.north_star.principles == []

    def test_live_platform_yaml_bootstrap_exemption_set(self) -> None:
        """Asserts the per-item bootstrap_completion_exempt set in the live YAML
        matches the canonical expected set verbatim (Part 8C of
        docs/INTENT-pre-codegen-contract-ratification.md)."""
        roadmap = Path(__file__).parent.parent / "docs" / "ROADMAP-PLATFORM.yaml"
        doc = load(roadmap)
        expected = {
            "T-1.0",
            "T-1.1",
            "T-1.2",
            "T-1.3",
            "T-1.4",
            "T-1.5",
            "T-1.6",
            "T0.6",
            "T0.7a",
            "T0.7b",
            "T0.7c",
            "T0.8",
            "T0.9",
            "T0.11",
            "T0.12",
            "T0.13",
            "T0.14",
            "T-1.11",
            "T-1.12",
            "T-1.13",
            "T-1.14",
            "T-1.15",
            "T-1.16",
            "T-1.17",
            "T-1.18",
            "T-1.19",
            "T0.12.5",
            "T0.12.6",
            "T0.12.7",
            # Migration-realized items (platform-roadmap-reconciliation 2026-05-31):
            # same circular ratification bind as the 29 items above -- T0.7b not yet built.
            "T0.2",
            "T0.3",
            "T0.5",
            "T2.1",
            "T2.2",
            "T2.3",
            "T2.10",
            "T2.13",
            # Scope (c) realized-ahead-of-ratification additions (2026-06-09 roadmap audit
            # integration, finding F-002): items completed under pending gating CDs that
            # ratify post-hoc via the ops portal vehicle. Exemption ends when the gating
            # CD ratifies (CD.5/CD.8+CD.15/CD.20/CD.34 respectively).
            "T0.10",
            "T2.4",
            "T2.5",
            "T2.12",
            "T2.16b",
            "T2.17",
        }
        actual = {item.id for item in doc.tier_items if item.bootstrap_completion_exempt}
        assert actual == expected, f"missing={expected - actual} extra={actual - expected}"

    def test_live_platform_yaml_cd25_present(self) -> None:
        """Asserts CD.25 is present with correct shape per INTENT v4 Part 7."""
        roadmap = Path(__file__).parent.parent / "docs" / "ROADMAP-PLATFORM.yaml"
        doc = load(roadmap)
        cd25 = next((c for c in doc.candidate_decisions if c.id == "CD.25"), None)
        assert cd25 is not None, "CD.25 missing from candidate_decisions[]"
        assert cd25.state == "pending"
        assert cd25.bootstrap_allowance is True
        assert isinstance(cd25.decision_required_before, list)
        assert len(cd25.decision_required_before) >= 1

    def test_live_platform_yaml_t112_collision_resolved(self) -> None:
        """Asserts T1.12 is the Class B Lambda ratification wave, T1.13 is CI-RCA."""
        roadmap = Path(__file__).parent.parent / "docs" / "ROADMAP-PLATFORM.yaml"
        doc = load(roadmap)
        by_id = {item.id: item for item in doc.tier_items}
        assert "T1.12" in by_id, "T1.12 (Class B Lambda ratification wave) missing"
        assert "Class B" in by_id["T1.12"].name, by_id["T1.12"].name
        assert "T1.13" in by_id, "T1.13 (CI-RCA methodology contract) missing"
        assert "CI-RCA" in by_id["T1.13"].name, by_id["T1.13"].name


# ---------------------------------------------------------------------------
# TestDeferredPostMvp -- Decision 93 / PLAN-platform-mvp-boundary
# ---------------------------------------------------------------------------


class TestDeferredPostMvp:
    def _make_doc(self, items: list[dict]) -> RoadmapDocument:
        return RoadmapDocument.model_validate(_doc(tier_items=items))

    def test_deferred_item_absent_from_eligible(self) -> None:
        """(a) deferred_post_mvp item is absent from eligible_items() and next_eligible."""
        doc = self._make_doc([{**_item("T0.1"), "status": "deferred_post_mvp"}])
        state = PlatformRoadmapState(doc)
        eligible_ids = {i.id for i in state.eligible_items()}
        assert "T0.1" not in eligible_ids
        full = state.to_preflight_dict()
        next_ids = {i["id"] for i in full["next_eligible"]}
        assert "T0.1" not in next_ids

    def test_tier_complete_with_deferred_item(self) -> None:
        """(b) tier [complete, deferred_post_mvp] counts as complete; active_tier advances."""
        doc = self._make_doc(
            [
                _item("T0.1", tier="T0", status="complete"),
                {**_item("T0.2", tier="T0"), "status": "deferred_post_mvp"},
                _item("T1.1", tier="T1"),
            ]
        )
        state = PlatformRoadmapState(doc)
        assert state.tier_complete("T0") is True
        assert state.active_tier() == "T1"

    def test_live_dep_on_deferred_raises(self) -> None:
        """(c) not_started item depending on deferred_post_mvp item raises ValueError."""
        d = _doc(
            tier_items=[
                {**_item("T0.1"), "status": "deferred_post_mvp"},
                _item("T0.2", depends_on=["T0.1"]),
            ]
        )
        with pytest.raises(ValueError, match="deferred_post_mvp"):
            RoadmapDocument.model_validate(d)

    def test_in_progress_dep_on_deferred_raises(self) -> None:
        """(c-ext) in_progress item depending on deferred_post_mvp item also raises ValueError."""
        d = _doc(
            tier_items=[
                {**_item("T0.1"), "status": "deferred_post_mvp"},
                {**_item("T0.2", depends_on=["T0.1"]), "status": "in_progress"},
            ]
        )
        with pytest.raises(ValueError, match="deferred_post_mvp"):
            RoadmapDocument.model_validate(d)

    def test_deferred_bucket_in_full_state_absent_from_slim(self) -> None:
        """(d) deferred item in deferred_post_mvp bucket of full state; absent from slim."""
        doc = self._make_doc([{**_item("T0.1"), "status": "deferred_post_mvp"}])
        state = PlatformRoadmapState(doc)
        full = state.to_preflight_dict()
        assert "deferred_post_mvp" in full
        assert any(i["id"] == "T0.1" for i in full["deferred_post_mvp"])
        # session_preflight._slim_roadmap_state must NOT include deferred_post_mvp
        slim = _slim_roadmap_state(full)
        assert "deferred_post_mvp" not in slim

    def test_real_roadmap_parked_ids_absent_from_next_eligible(self) -> None:
        """(e) four parked ids (T2.8/T2.9/T2.11a/T2.11b) absent from next_eligible in real roadmap."""
        roadmap = Path(__file__).parent.parent / "docs" / "ROADMAP-PLATFORM.yaml"
        doc = load(roadmap)
        state = PlatformRoadmapState(doc)
        eligible_ids = {i.id for i in state.eligible_items()}
        parked_ids = {"T2.8", "T2.9", "T2.11a", "T2.11b"}
        assert parked_ids.isdisjoint(eligible_ids), f"Parked items found in eligible: {parked_ids & eligible_ids}"


# ---------------------------------------------------------------------------
# Helpers for T-1.20 tests
# ---------------------------------------------------------------------------


def _cd(cd_id: str, state: str = "pending", gates: list | None = None) -> dict:
    return {"id": cd_id, "title": f"Decision {cd_id}", "state": state, "gates": gates or []}


def _state_from_doc(doc_dict: dict) -> PlatformRoadmapState:
    return PlatformRoadmapState(RoadmapDocument.model_validate(doc_dict))


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


# ---------------------------------------------------------------------------
# TestBlockedOnCd -- T-1.20: three sources + exempt annotation
# ---------------------------------------------------------------------------


class TestBlockedOnCd:
    def test_related_cd_source(self) -> None:
        doc = _doc(
            tier_items=[{**_item("T0.1"), "related_candidate_decisions": ["CD.99"]}],
            candidate_decisions=[_cd("CD.99")],
        )
        result = _state_from_doc(doc).blocked_on_cd()
        assert len(result) == 1
        r = result[0]
        assert r["id"] == "T0.1"
        assert "CD.99" in r["blocking_cds"]
        assert r["relationships"]["CD.99"] == "related"

    def test_gates_item_ref_source(self) -> None:
        doc = _doc(
            tier_items=[_item("T0.1")],
            candidate_decisions=[_cd("CD.99", gates=["T0.1"])],
        )
        result = _state_from_doc(doc).blocked_on_cd()
        assert len(result) == 1
        r = result[0]
        assert r["id"] == "T0.1"
        assert r["relationships"]["CD.99"] == "gates"

    def test_gates_tier_shortcut_source(self) -> None:
        doc = _doc(
            tier_items=[_item("T0.1", tier="T0")],
            candidate_decisions=[_cd("CD.99", gates=["T0"])],
        )
        result = _state_from_doc(doc).blocked_on_cd()
        assert any(r["id"] == "T0.1" for r in result)
        r = next(r for r in result if r["id"] == "T0.1")
        assert r["relationships"]["CD.99"] == "gates"

    def test_decision_required_before_source(self) -> None:
        doc = _doc(
            tier_items=[{**_item("T0.1"), "decision_required_before": ["CD.99 must ratify first"]}],
            candidate_decisions=[_cd("CD.99")],
        )
        result = _state_from_doc(doc).blocked_on_cd()
        assert len(result) == 1
        r = result[0]
        assert r["id"] == "T0.1"
        assert r["relationships"]["CD.99"] == "decision_required_before"

    def test_no_pending_cds_empty_result(self) -> None:
        doc = _doc(
            tier_items=[{**_item("T0.1"), "related_candidate_decisions": ["CD.99"]}],
            candidate_decisions=[_cd("CD.99", state="ratified")],
        )
        result = _state_from_doc(doc).blocked_on_cd()
        assert result == []

    def test_ratified_cd_not_blocking(self) -> None:
        doc = _doc(
            tier_items=[{**_item("T0.1"), "related_candidate_decisions": ["CD.99"]}],
            candidate_decisions=[_cd("CD.99", state="ratified")],
        )
        result = _state_from_doc(doc).blocked_on_cd()
        assert not any(r["id"] == "T0.1" for r in result)

    def test_bootstrap_completion_exempt_annotation(self) -> None:
        doc = _doc(
            tier_items=[{**_item("T0.1"), "related_candidate_decisions": ["CD.99"], "bootstrap_completion_exempt": True}],
            candidate_decisions=[_cd("CD.99")],
        )
        result = _state_from_doc(doc).blocked_on_cd()
        assert len(result) == 1
        assert result[0]["bootstrap_completion_exempt"] is True

    def test_non_eligible_item_excluded(self) -> None:
        # T0.1 blocked by T0.2 (not complete) -> not in eligible_items -> not in blocked_on_cd
        doc = _doc(
            tier_items=[
                {**_item("T0.1", depends_on=["T0.2"]), "related_candidate_decisions": ["CD.99"]},
                _item("T0.2"),
            ],
            candidate_decisions=[_cd("CD.99")],
        )
        result = _state_from_doc(doc).blocked_on_cd()
        assert not any(r["id"] == "T0.1" for r in result)

    def test_first_source_wins(self) -> None:
        # Item has CD.99 in both related_candidate_decisions (source 1) and cd.gates (source 2).
        # "related" must win because it is processed first and the guard `if cd_id not in blocking`
        # prevents overwrite.
        doc = _doc(
            tier_items=[{**_item("T0.1"), "related_candidate_decisions": ["CD.99"]}],
            candidate_decisions=[_cd("CD.99", gates=["T0.1"])],
        )
        result = _state_from_doc(doc).blocked_on_cd()
        assert len(result) == 1
        assert result[0]["relationships"]["CD.99"] == "related"

    def test_blocking_cds_sorted(self) -> None:
        # Multiple pending CDs; blocking_cds[] must be sorted for deterministic output.
        doc = _doc(
            tier_items=[{**_item("T0.1"), "related_candidate_decisions": ["CD.99", "CD.13"]}],
            candidate_decisions=[_cd("CD.99"), _cd("CD.13")],
        )
        result = _state_from_doc(doc).blocked_on_cd()
        assert len(result) == 1
        assert result[0]["blocking_cds"] == sorted(result[0]["blocking_cds"])


# ---------------------------------------------------------------------------
# TestUserActionRequired -- T-1.20: user_action_required threading
# ---------------------------------------------------------------------------


class TestUserActionRequired:
    def test_user_action_required_true_in_item_dict(self) -> None:
        doc = _doc(tier_items=[{**_item("T0.1"), "user_action_required": True}])
        state = _state_from_doc(doc)
        full = state.to_preflight_dict()
        item = next(i for i in full["next_eligible"] if i["id"] == "T0.1")
        assert item["user_action_required"] is True

    def test_user_action_required_none_default(self) -> None:
        doc = _doc(tier_items=[_item("T0.1")])
        state = _state_from_doc(doc)
        full = state.to_preflight_dict()
        item = next(i for i in full["next_eligible"] if i["id"] == "T0.1")
        assert item["user_action_required"] is None

    def test_user_action_required_false(self) -> None:
        doc = _doc(tier_items=[{**_item("T0.1"), "user_action_required": False}])
        state = _state_from_doc(doc)
        full = state.to_preflight_dict()
        item = next(i for i in full["next_eligible"] if i["id"] == "T0.1")
        assert item["user_action_required"] is False


# ---------------------------------------------------------------------------
# TestLiveGateEvaluations -- T-1.20 live-YAML anchors
# ---------------------------------------------------------------------------

_LIVE_ROADMAP = Path(__file__).parent.parent / "docs" / "ROADMAP-PLATFORM.yaml"


@pytest.mark.skipif(not _LIVE_ROADMAP.exists(), reason="live ROADMAP-PLATFORM.yaml not present")
class TestLiveGateEvaluations:
    def _result(self):  # type: ignore[return]
        return compute_state_dict(_LIVE_ROADMAP)

    def test_all_four_gates_have_verdict(self) -> None:
        gates = {g["id"]: g for g in self._result().get("gate_evaluations", [])}
        for gid in ("G.1", "G.8", "G.9", "G.10"):
            assert gid in gates, f"gate {gid} missing from gate_evaluations"
            assert "verdict" in gates[gid], f"gate {gid} missing 'verdict' key"
            assert gates[gid]["verdict"] in ("pass", "fail", "deferred")

    def test_g1_passes(self) -> None:
        # T-1.4 and T-1.5 are both complete -> G.1 must pass
        gates = {g["id"]: g for g in self._result().get("gate_evaluations", [])}
        g1 = gates.get("G.1")
        assert g1 is not None
        assert g1["verdict"] == "pass", f"G.1: T-1.4 and T-1.5 are complete so rule must pass: {g1}"

    def test_g8_fails(self) -> None:
        # T3.2 is not_started -> first conjunct of G.8 fails -> Kleene AND -> fail
        gates = {g["id"]: g for g in self._result().get("gate_evaluations", [])}
        g8 = gates.get("G.8")
        assert g8 is not None
        assert g8["verdict"] == "fail", f"G.8: T3.2 not_started so first conjunct must fail: {g8}"

    def test_g9_non_deferred(self) -> None:
        # T4.2 is not_started -> verdict is fail (not deferred)
        gates = {g["id"]: g for g in self._result().get("gate_evaluations", [])}
        g9 = gates.get("G.9")
        assert g9 is not None
        assert g9["verdict"] in ("pass", "fail"), f"G.9 verdict must not be deferred: {g9}"

    def test_g10_non_deferred(self) -> None:
        # T2.1/T2.2/T2.3 statuses are statically resolvable; grace_period_elapsed is computable
        gates = {g["id"]: g for g in self._result().get("gate_evaluations", [])}
        g10 = gates.get("G.10")
        assert g10 is not None
        assert g10["verdict"] in ("pass", "fail"), f"G.10 verdict must not be deferred: {g10}"

    def test_blocked_on_cd_non_empty(self) -> None:
        # The live roadmap always carries not_started eligible items gated by a pending CD
        # (e.g. the T-1 contract-wave items under pending CD.1/CD.25). Anchored on the
        # invariant rather than a specific id so this plan's own bookkeeping (which may
        # flip an anchor item out of eligible) does not make the regression test fragile.
        result = self._result()
        assert result.get("blocked_on_cd"), "expected at least one blocked-on-CD item on the live roadmap"

    def test_blocked_on_cd_references_only_pending_cds(self) -> None:
        # Core semantic invariant: blocked_on_cd never surfaces a ratified/non-pending CD.
        doc = load(_LIVE_ROADMAP)
        pending = {cd.id for cd in doc.candidate_decisions if cd.state == "pending"}
        for entry in self._result().get("blocked_on_cd", []):
            for cd_id in entry["blocking_cds"]:
                assert cd_id in pending, f"{entry['id']} blocked on non-pending CD {cd_id}"

    def test_blocked_on_cd_relationships_are_valid_types(self) -> None:
        valid = {"related", "gates", "decision_required_before"}
        for entry in self._result().get("blocked_on_cd", []):
            for cd_id, rel in entry["relationships"].items():
                assert rel in valid, f"{entry['id']} CD {cd_id} has invalid relationship {rel!r}"

    def test_blocked_on_cd_items_have_required_keys(self) -> None:
        result = self._result()
        for entry in result.get("blocked_on_cd", []):
            for key in ("id", "name", "blocking_cds", "relationships", "bootstrap_completion_exempt"):
                assert key in entry, f"blocked_on_cd entry {entry.get('id')} missing key '{key}'"
            assert isinstance(entry["blocking_cds"], list)
            assert isinstance(entry["relationships"], dict)


# ---------------------------------------------------------------------------
# TestExitCriterionNormalizer -- T-1.23
# ---------------------------------------------------------------------------


class TestExitCriterionNormalizer:
    """Bare strings normalize to ExitCriterion(status='open'); structured dicts pass through."""

    def test_bare_string_becomes_exit_criterion(self) -> None:
        item = TierItem(id="X", tier="T0", name="t", exit_criteria=["do something"])
        assert len(item.exit_criteria) == 1
        assert isinstance(item.exit_criteria[0], ExitCriterion)
        assert item.exit_criteria[0].id == "c1"
        assert item.exit_criteria[0].text == "do something"
        assert item.exit_criteria[0].status == "open"
        assert item.exit_criteria[0].met_by is None

    def test_multiple_bare_strings_get_sequential_ids(self) -> None:
        item = TierItem(id="X", tier="T0", name="t", exit_criteria=["a", "b", "c"])
        ids = [c.id for c in item.exit_criteria]
        assert ids == ["c1", "c2", "c3"]

    def test_structured_dict_passes_through(self) -> None:
        item = TierItem(
            id="X",
            tier="T0",
            name="t",
            exit_criteria=[{"id": "c1", "text": "done", "status": "open"}],
        )
        assert isinstance(item.exit_criteria[0], ExitCriterion)
        assert item.exit_criteria[0].id == "c1"
        assert item.exit_criteria[0].text == "done"

    def test_empty_exit_criteria(self) -> None:
        item = TierItem(id="X", tier="T0", name="t", exit_criteria=[])
        assert item.exit_criteria == []

    def test_exit_criterion_model_status_enum(self) -> None:
        for s in ("open", "met", "rehomed"):
            ec = ExitCriterion(id="c1", text="x", status=s, met_by="something" if s != "open" else None)
            assert ec.status == s

    def test_exit_criterion_rejects_unknown_field(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ExitCriterion(id="c1", text="x", bogus_field="y")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# TestExitCriteriaIntegrity -- model_validator checks (g) and (h)
# ---------------------------------------------------------------------------


class TestExitCriteriaIntegrity:
    """met/rehomed without met_by -> ValueError; rehomed met_by to unknown item -> ValueError."""

    def _doc_with_items(self, *items: dict) -> dict:
        d = copy.deepcopy(_BASE_DOC)
        d["tier_items"] = list(items)
        return d

    def test_met_criterion_requires_met_by(self) -> None:
        from pydantic import ValidationError

        item = _item("A")
        item["exit_criteria"] = [{"id": "c1", "text": "x", "status": "met"}]
        with pytest.raises(ValidationError, match="met_by"):
            RoadmapDocument.model_validate(self._doc_with_items(item))

    def test_rehomed_criterion_requires_met_by(self) -> None:
        from pydantic import ValidationError

        item = _item("A")
        item["exit_criteria"] = [{"id": "c1", "text": "x", "status": "rehomed"}]
        with pytest.raises(ValidationError, match="met_by"):
            RoadmapDocument.model_validate(self._doc_with_items(item))

    def test_rehomed_met_by_must_resolve_to_known_item(self) -> None:
        from pydantic import ValidationError

        item = _item("A")
        item["exit_criteria"] = [{"id": "c1", "text": "x", "status": "rehomed", "met_by": "Z.99"}]
        with pytest.raises(ValidationError, match="does not resolve to a known tier_item id"):
            RoadmapDocument.model_validate(self._doc_with_items(item))

    def test_rehomed_met_by_valid_item_passes(self) -> None:
        item_a = _item("A")
        item_a["exit_criteria"] = [{"id": "c1", "text": "x", "status": "rehomed", "met_by": "B"}]
        item_b = _item("B")
        doc = RoadmapDocument.model_validate(self._doc_with_items(item_a, item_b))
        assert doc.tier_items[0].exit_criteria[0].status == "rehomed"
        assert doc.tier_items[0].exit_criteria[0].met_by == "B"

    def test_met_with_valid_met_by_passes(self) -> None:
        item = _item("A")
        item["exit_criteria"] = [{"id": "c1", "text": "x", "status": "met", "met_by": "some-plan-slug"}]
        doc = RoadmapDocument.model_validate(self._doc_with_items(item))
        assert doc.tier_items[0].exit_criteria[0].status == "met"


# ---------------------------------------------------------------------------
# TestComputeFollowonState -- T-1.23
# ---------------------------------------------------------------------------


class TestComputeFollowonState:
    """compute_followon_state: in-flight plan vs no plan; live-items-only scoping."""

    def _make_doc(self, items: list[dict]) -> RoadmapDocument:
        d = copy.deepcopy(_BASE_DOC)
        d["tier_items"] = items
        return RoadmapDocument.model_validate(d)

    def _in_progress_item(self, item_id: str, criteria: list[dict]) -> dict:
        item = _item(item_id, status="in_progress")
        item["exit_criteria"] = criteria
        return item

    def test_no_plan_needs_followon(self, tmp_path: Path) -> None:
        doc = self._make_doc([self._in_progress_item("A", [{"id": "c1", "text": "x", "status": "open"}])])
        result = compute_followon_state(doc, tmp_path)
        assert result["A"]["open_criteria_count"] == 1
        assert result["A"]["all_plans_actioned"] is True
        assert result["A"]["needs_followon_plan"] is True

    def test_in_flight_plan_suppresses_followon(self, tmp_path: Path) -> None:
        doc = self._make_doc([self._in_progress_item("A", [{"id": "c1", "text": "x", "status": "open"}])])
        plan_data = {
            "schema_version": 1,
            "slug": "test-plan",
            "intent": "test",
            "plan_type": "IMPLEMENTATION",
            "verification_tier": "V1",
            "plan_path": "docs/plans/PLAN-test-plan.yaml",
            "phase": "T0",
            "scope": [{"file": "f.py", "action": "Modify", "purpose": "p"}],
            "acceptance_criteria": ["ac"],
            "verification_plan": [
                {"step": 1, "phase": "pre-deploy", "action": "a", "command": "echo x", "expected": "x", "fix_if": "f"}
            ],
            "execution_steps": ["step 1"],
            "closes_criteria": ["A:c1"],
        }
        plan_file = tmp_path / "PLAN-test-plan.yaml"
        plan_file.write_text(__import__("yaml").dump(plan_data))
        result = compute_followon_state(doc, tmp_path)
        assert result["A"]["open_criteria_count"] == 1
        assert result["A"]["all_plans_actioned"] is False
        assert result["A"]["needs_followon_plan"] is False

    def test_zero_open_criteria_no_followon_needed(self, tmp_path: Path) -> None:
        doc = self._make_doc(
            [
                self._in_progress_item(
                    "A",
                    [
                        {"id": "c1", "text": "x", "status": "met", "met_by": "some-plan"},
                        {"id": "c2", "text": "y", "status": "rehomed", "met_by": "B"},
                    ],
                ),
                _item("B"),
            ]
        )
        result = compute_followon_state(doc, tmp_path)
        assert result["A"]["open_criteria_count"] == 0
        assert result["A"]["needs_followon_plan"] is False

    def test_deferred_post_mvp_excluded(self, tmp_path: Path) -> None:
        deferred = _item("D", status="deferred_post_mvp")
        deferred["exit_criteria"] = [{"id": "c1", "text": "x", "status": "open"}]
        doc = self._make_doc([_item("A", status="not_started"), deferred])
        result = compute_followon_state(doc, tmp_path)
        assert "D" not in result, "deferred_post_mvp items must not appear in followon state"

    def test_not_started_excluded(self, tmp_path: Path) -> None:
        doc = self._make_doc([_item("A", status="not_started")])
        result = compute_followon_state(doc, tmp_path)
        assert "A" not in result, "not_started items must not appear in followon state"

    def test_malformed_plan_skipped(self, tmp_path: Path) -> None:
        doc = self._make_doc([self._in_progress_item("A", [{"id": "c1", "text": "x", "status": "open"}])])
        (tmp_path / "PLAN-bad.yaml").write_text("invalid: [yaml: {content")
        result = compute_followon_state(doc, tmp_path)
        assert result["A"]["needs_followon_plan"] is True

    def test_plan_closes_different_item_does_not_suppress(self, tmp_path: Path) -> None:
        doc = self._make_doc(
            [
                self._in_progress_item("A", [{"id": "c1", "text": "x", "status": "open"}]),
                self._in_progress_item("B", [{"id": "c1", "text": "y", "status": "open"}]),
            ]
        )
        plan_data = {
            "schema_version": 1,
            "slug": "only-b",
            "intent": "x",
            "plan_type": "IMPLEMENTATION",
            "verification_tier": "V1",
            "plan_path": "docs/plans/PLAN-only-b.yaml",
            "phase": "T0",
            "scope": [{"file": "f.py", "action": "Modify", "purpose": "p"}],
            "acceptance_criteria": ["ac"],
            "verification_plan": [
                {"step": 1, "phase": "pre-deploy", "action": "a", "command": "echo x", "expected": "x", "fix_if": "f"}
            ],
            "execution_steps": ["step 1"],
            "closes_criteria": ["B:c1"],
        }
        (tmp_path / "PLAN-only-b.yaml").write_text(__import__("yaml").dump(plan_data))
        result = compute_followon_state(doc, tmp_path)
        assert result["A"]["needs_followon_plan"] is True, "A's criterion not covered by the B plan"
        assert result["B"]["needs_followon_plan"] is False, "B's criterion is covered"
