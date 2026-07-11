"""Tests for scripts/platform_roadmap_models.py: Pydantic schema and graph validation."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from scripts.roadmap.platform_roadmap import (
    ExitCriterion,
    KnownGap,
    OpenQuestion,
    PlatformRoadmapState,
    RoadmapDocument,
    TierItem,
    load,
)
from scripts.session.preflight import _slim_roadmap_state

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
        docs/INTENT-pre-codegen-contract-ratification.md).

        close-audit-ulf-02 (2026-07-03): CD.1/CD.2/CD.13/CD.20/CD.21/CD.26 ratified
        (Decisions 108-113). Strips the 16 discharged items whose gating CDs are now
        ALL ratified (43 -> 27): T-1.0, T-1.1, T-1.2, T-1.3, T-1.4, T-1.5, T-1.6, T0.2,
        T0.5, T0.11, T0.14, T2.3, T2.10, T2.12, T2.13, T2.16b. Every other exempt item
        (still gated by a pending CD.25/CD.10/CD.12/CD.4/CD.5/CD.8/CD.15/CD.34 -- e.g.
        T0.3 is ALSO gated by pending CD.10, so it stays despite CD.26 ratifying) is
        retained verbatim.
        """
        roadmap = Path(__file__).parent.parent / "docs" / "ROADMAP-PLATFORM.yaml"
        doc = load(roadmap)
        expected = {
            "T0.6",
            "T0.7a",
            "T0.7b",
            "T0.7c",
            "T0.8",
            "T0.9",
            "T0.12",
            "T0.13",
            "T0.12.5",
            "T0.12.7",
            # Migration-realized items (platform-roadmap-reconciliation 2026-05-31):
            # same circular ratification bind as the items above -- T0.7b not yet built.
            "T0.3",
            "T2.1",
            "T2.2",
            # Scope (c) realized-ahead-of-ratification additions (2026-06-09 roadmap audit
            # integration, finding F-002): items completed under pending gating CDs that
            # ratify post-hoc via the ops portal vehicle. Exemption ends when the gating
            # CD ratifies (CD.5/CD.8+CD.15/CD.34 respectively; CD.2/CD.20/CD.21/CD.26 slices
            # discharged by close-audit-ulf-02, see docstring above).
            "T0.10",
            "T2.4",
            "T2.5",
            "T2.17",
        }
        # dec-118 (Ratify CD.25, 2026-07-03) discharged the CD.25-scoped exemption for
        # the 10 items gated solely by CD.25 (T-1.11..T-1.19, T0.12.6); they are no
        # longer bootstrap_completion_exempt. T0.12.5 (CD.29) and T0.12.7 (CD.10) remain
        # exempt -- gated by other still-pending CDs.
        actual = {item.id for item in doc.tier_items if item.bootstrap_completion_exempt}
        assert actual == expected, f"missing={expected - actual} extra={actual - expected}"

    def test_live_platform_yaml_cd25_present(self) -> None:
        """Asserts CD.25 is present with correct shape per INTENT v4 Part 7."""
        roadmap = Path(__file__).parent.parent / "docs" / "ROADMAP-PLATFORM.yaml"
        doc = load(roadmap)
        cd25 = next((c for c in doc.candidate_decisions if c.id == "CD.25"), None)
        assert cd25 is not None, "CD.25 missing from candidate_decisions[]"
        assert cd25.state == "ratified"
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
# TestOpenQuestionKnownGapLifecycle -- PLAN-close-audit-ulf-04-ulf-10 (Decision 114)
# ---------------------------------------------------------------------------


class TestOpenQuestionKnownGapLifecycle:
    """status/resolution_ref lifecycle fields on OpenQuestion and KnownGap (checks (i)/(j))."""

    def _doc_with_oq(self, *oqs: dict) -> dict:
        d = copy.deepcopy(_BASE_DOC)
        d["open_questions"] = list(oqs)
        return d

    def _doc_with_kg(self, *kgs: dict) -> dict:
        d = copy.deepcopy(_BASE_DOC)
        d["known_gaps"] = list(kgs)
        return d

    def test_open_question_status_enum_accepted(self) -> None:
        for s in ("open", "resolved", "closed", "promoted"):
            oq = OpenQuestion(id="OQ.1", question="q", status=s, resolution_ref="x" if s != "open" else None)
            assert oq.status == s

    def test_known_gap_status_enum_accepted(self) -> None:
        for s in ("open", "resolved", "closed", "promoted"):
            kg = KnownGap(id="KG.1", gap="g", status=s, resolution_ref="x" if s != "open" else None)
            assert kg.status == s

    def test_open_question_invalid_status_raises(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            OpenQuestion(id="OQ.1", question="q", status="bogus")  # type: ignore[arg-type]

    def test_known_gap_invalid_status_raises(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            KnownGap(id="KG.1", gap="g", status="bogus")  # type: ignore[arg-type]

    def test_open_question_defaults_to_open_no_resolution_ref(self) -> None:
        oq = OpenQuestion(id="OQ.1", question="q")
        assert oq.status == "open"
        assert oq.resolution_ref is None

    def test_known_gap_non_open_without_resolution_ref_raises(self) -> None:
        from pydantic import ValidationError

        d = self._doc_with_kg({"id": "KG.1", "gap": "g", "status": "resolved"})
        with pytest.raises(ValidationError, match="resolution_ref"):
            RoadmapDocument.model_validate(d)

    def test_open_question_non_open_without_resolution_ref_raises(self) -> None:
        from pydantic import ValidationError

        d = self._doc_with_oq({"id": "OQ.1", "question": "q", "status": "resolved"})
        with pytest.raises(ValidationError, match="resolution_ref"):
            RoadmapDocument.model_validate(d)

    def test_open_question_non_open_with_resolution_ref_passes(self) -> None:
        d = self._doc_with_oq({"id": "OQ.1", "question": "q", "status": "resolved", "resolution_ref": "T0.9"})
        doc = RoadmapDocument.model_validate(d)
        assert doc.open_questions[0].status == "resolved"
        assert doc.open_questions[0].resolution_ref == "T0.9"

    def test_known_gap_non_open_with_resolution_ref_passes(self) -> None:
        d = self._doc_with_kg({"id": "KG.1", "gap": "g", "status": "promoted", "resolution_ref": "CD.18"})
        doc = RoadmapDocument.model_validate(d)
        assert doc.known_gaps[0].status == "promoted"
        assert doc.known_gaps[0].resolution_ref == "CD.18"

    def test_open_question_open_status_no_resolution_ref_required(self) -> None:
        d = self._doc_with_oq({"id": "OQ.1", "question": "q", "status": "open"})
        doc = RoadmapDocument.model_validate(d)
        assert doc.open_questions[0].status == "open"
        assert doc.open_questions[0].resolution_ref is None

    def test_live_roadmap_loads_clean(self) -> None:
        roadmap = Path(__file__).parent.parent / "docs" / "ROADMAP-PLATFORM.yaml"
        doc = load(roadmap)
        non_open_oq = [q for q in doc.open_questions if q.status != "open"]
        non_open_kg = [g for g in doc.known_gaps if g.status != "open"]
        assert len(non_open_oq) == 11
        assert len(non_open_kg) == 4
        for entry in (*non_open_oq, *non_open_kg):
            assert entry.resolution_ref, f"{entry.id} has non-open status but no resolution_ref"


# ---------------------------------------------------------------------------
# TestModelsCoverageTopUp -- closes per-file coverage gaps identified by code
# review after the platform_roadmap decomposition (coverage partition risk,
# rec-2633). test_cd_bad_gate_ref_raises and test_gate_rule_rejected_in_model
# now live in test_platform_roadmap_gate_rules.py (their natural home post-
# decomposition), which orphaned models.py's own _validate_graph raise-branch
# coverage from THIS suite's run. These are fresh, independently-written cases
# for the same raise sites -- not moved from the gate_rules suite.
# ---------------------------------------------------------------------------


class TestModelsCoverageTopUp:
    def test_cd_gate_ref_does_not_resolve_raises(self) -> None:
        # _validate_graph check (d): candidate_decisions[].gates entries must
        # resolve to a known tier_item id or tier shortcut.
        d = _doc(candidate_decisions=[{"id": "CD.X", "title": "T", "gates": ["T999.0"]}])
        with pytest.raises(Exception, match="does not resolve"):
            RoadmapDocument.model_validate(d)

    def test_cross_tier_gate_bad_rule_raises(self) -> None:
        # _validate_graph check (e): cross_tier_gates[].rule must validate
        # against the gate_helpers grammar; GateRuleParser's ValueError is
        # caught and re-raised with CrossTierGate context.
        d = _doc(cross_tier_gates=[{"id": "G.X", "name": "test", "rule": "bogus_helper(T0.1)", "rationale": "test"}])
        with pytest.raises(Exception, match="CrossTierGate 'G.X'"):
            RoadmapDocument.model_validate(d)

    def test_exit_criteria_non_list_input_short_circuits_normalizer(self) -> None:
        # _normalize_exit_criteria's mode="before" guard ("if not isinstance(v,
        # list): return v") returns non-list input unchanged; pydantic's own
        # list-type check then rejects it downstream -- proving the guard
        # clause itself executed rather than the per-item string-promotion loop.
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="valid list"):
            TierItem(id="X", tier="T0", name="t", exit_criteria=42)  # type: ignore[arg-type]
