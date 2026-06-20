"""Tests for scripts/platform_roadmap.py covering all T-1.5 exit criteria."""

from __future__ import annotations

import copy
import tempfile
from pathlib import Path

import pytest
import yaml

from scripts.platform_roadmap import (
    _GATE_HELPERS,
    GateRuleParser,
    PlatformRoadmapState,
    RoadmapDocument,
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
