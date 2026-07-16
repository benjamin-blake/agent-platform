"""Tests for scripts/platform_roadmap_state.py: eligibility, blocking, tier-shortcut resolution,
active-tier, internal PlatformRoadmapState helpers, and blocked-on-cd surfacing.

Migrated from the retired tests/test_platform_roadmap_state.py monolith (Decision 128
decompose-don't-raise / Decision 131 mirror convention). Shared fixture helpers live in
tests/fixtures/platform_roadmap_state.py -- never import from a sibling test_*.py module.
"""

from __future__ import annotations

from pathlib import Path

from scripts.roadmap.platform_roadmap import PlatformRoadmapState, RoadmapDocument
from tests.fixtures.platform_roadmap_state import _cd, _doc, _item, _make_state, _state_from_doc

# ---------------------------------------------------------------------------
# TestEligibleItems
# ---------------------------------------------------------------------------


class TestEligibleItems:
    def test_eligible_items(self) -> None:
        # T0.1 depends on T0.dep which is complete -> eligible
        # T0.2 depends on T0.missing which is not_started -> NOT eligible (blocked)
        state = _make_state(
            [
                _item("T0.dep", status="complete"),
                _item("T0.not-done"),
                _item("T0.1", depends_on=["T0.dep"]),
                _item("T0.2", depends_on=["T0.not-done"]),
            ]
        )
        eligible_ids = {i.id for i in state.eligible_items()}
        assert "T0.1" in eligible_ids
        assert "T0.2" not in eligible_ids
        assert "T0.dep" not in eligible_ids  # complete, not not_started
        assert "T0.not-done" in eligible_ids  # no deps, not_started


# ---------------------------------------------------------------------------
# TestComputeBlocked
# ---------------------------------------------------------------------------


class TestComputeBlocked:
    def test_compute_blocked(self) -> None:
        state = _make_state(
            [
                _item("T0.dep"),  # not_started, unsatisfied
                _item("T0.blocked", depends_on=["T0.dep"]),
                _item("T0.free"),
            ]
        )
        blocked = state.compute_blocked()
        blocked_ids = {i.id for i in blocked}
        assert blocked_ids == {"T0.blocked"}

    def test_blocked_on_surfaces_unsatisfied_deps(self) -> None:
        state = _make_state(
            [
                _item("T0.a"),
                _item("T0.b"),
                _item("T0.c", depends_on=["T0.a", "T0.b"]),
            ]
        )
        blocked = state.compute_blocked()
        assert len(blocked) == 1
        blocked_on = state._blocked_on(blocked[0])
        assert set(blocked_on) == {"T0.a", "T0.b"}

    def test_blocked_on_partial(self) -> None:
        # Only one dep is unsatisfied
        state = _make_state(
            [
                _item("T0.a", status="complete"),
                _item("T0.b"),
                _item("T0.c", depends_on=["T0.a", "T0.b"]),
            ]
        )
        blocked_on = state._blocked_on(state._by_id["T0.c"])
        assert blocked_on == ["T0.b"]


# ---------------------------------------------------------------------------
# TestStrategicPending
# ---------------------------------------------------------------------------


class TestStrategicPending:
    def test_strategic_pending(self) -> None:
        state = _make_state(
            [
                _item("T0.regular"),
                _item("T0.strat", strategic=True),
            ]
        )
        strategic = {i.id for i in state.strategic_pending_items()}
        assert "T0.strat" in strategic
        assert "T0.regular" not in strategic

    def test_strategic_absent_from_next_eligible_in_preflight_dict(self) -> None:
        state = _make_state(
            [
                _item("T0.regular"),
                _item("T0.strat", strategic=True),
            ]
        )
        d = state.to_preflight_dict()
        next_ids = {i["id"] for i in d["next_eligible"]}
        strategic_ids = {i["id"] for i in d["strategic_pending"]}
        assert "T0.strat" not in next_ids
        assert "T0.strat" in strategic_ids
        assert "T0.regular" in next_ids

    def test_strategic_blocked_item_absent_from_both(self) -> None:
        # A strategic item that is blocked should appear in blocked[], not strategic_pending[]
        state = _make_state(
            [
                _item("T0.dep"),
                _item("T0.strat", depends_on=["T0.dep"], strategic=True),
            ]
        )
        d = state.to_preflight_dict()
        strategic_ids = {i["id"] for i in d["strategic_pending"]}
        blocked_ids = {i["id"] for i in d["blocked"]}
        assert "T0.strat" not in strategic_ids
        assert "T0.strat" in blocked_ids


# ---------------------------------------------------------------------------
# TestTierShortcutResolution
# ---------------------------------------------------------------------------


class TestTierShortcutResolution:
    def test_tier_shortcut_blocked_when_tier_incomplete(self) -> None:
        state = _make_state(
            [
                _item("T0.1", tier="T0", status="complete"),
                _item("T0.2", tier="T0"),  # not_started -> T0 not complete
                _item("T1.1", tier="T1", depends_on=["T0"]),
            ]
        )
        blocked_ids = {i.id for i in state.compute_blocked()}
        assert "T1.1" in blocked_ids

    def test_tier_shortcut_eligible_when_tier_complete(self) -> None:
        state = _make_state(
            [
                _item("T0.1", tier="T0", status="complete"),
                _item("T0.2", tier="T0", status="complete"),
                _item("T1.1", tier="T1", depends_on=["T0"]),
            ]
        )
        eligible_ids = {i.id for i in state.eligible_items()}
        assert "T1.1" in eligible_ids

    def test_tier_shortcut_blocked_on_includes_tier_name(self) -> None:
        state = _make_state(
            [
                _item("T0.1", tier="T0"),  # not complete
                _item("T1.1", tier="T1", depends_on=["T0"]),
            ]
        )
        blocked = state.compute_blocked()
        assert len(blocked) == 1
        assert state._blocked_on(blocked[0]) == ["T0"]

    def test_tier_negative_shortcut(self) -> None:
        # T-1 tier shortcut (negative tier number)
        state = _make_state(
            [
                _item("T-1.1", tier="T-1", status="complete"),
                _item("T0.1", tier="T0", depends_on=["T-1"]),
            ]
        )
        eligible_ids = {i.id for i in state.eligible_items()}
        assert "T0.1" in eligible_ids


# ---------------------------------------------------------------------------
# TestActiveTier
# ---------------------------------------------------------------------------


class TestActiveTier:
    def test_active_tier_partial_t_minus_1(self) -> None:
        state = _make_state(
            [
                _item("T-1.1", tier="T-1", status="complete"),
                _item("T-1.2", tier="T-1"),  # not_started
                _item("T0.1", tier="T0"),
            ]
        )
        assert state.active_tier() == "T-1"

    def test_active_tier_skips_complete_tier(self) -> None:
        state = _make_state(
            [
                _item("T-1.1", tier="T-1", status="complete"),
                _item("T0.1", tier="T0"),  # not_started
            ]
        )
        assert state.active_tier() == "T0"

    def test_active_tier_null_when_all_complete(self) -> None:
        state = _make_state(
            [
                _item("T-1.1", tier="T-1", status="complete"),
                _item("T0.1", tier="T0", status="complete"),
            ]
        )
        assert state.active_tier() is None

    def test_active_tier_reserved_items_excluded(self) -> None:
        # A tier with only reserved items is treated as complete
        state = _make_state(
            [
                {**_item("T-1.1", tier="T-1"), "status": "reserved"},
                _item("T0.1", tier="T0"),
            ]
        )
        assert state.active_tier() == "T0"


# ---------------------------------------------------------------------------
# TestPlatformRoadmapState -- internal helpers (tier_complete, resolve_depends_on, ...)
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
# TestCompletionBlockedOnCd -- T-1.20:c6
# ---------------------------------------------------------------------------


class TestCompletionBlockedOnCd:
    """completion_blocked_on_cd field on in_progress items in to_preflight_dict."""

    def _make_state(self, items: list[dict], cds: list[dict] | None = None) -> PlatformRoadmapState:
        d = _doc(tier_items=items, candidate_decisions=cds or [])
        return PlatformRoadmapState(RoadmapDocument.model_validate(d))

    def test_completion_blocked_on_cd_non_exempt_with_pending_cd(self, tmp_path: Path) -> None:
        """in_progress item with pending related_candidate_decisions surfaces the CD id."""
        items = [{**_item("T0.1", status="in_progress"), "related_candidate_decisions": ["CD.99"]}]
        state = self._make_state(items, [_cd("CD.99")])
        result = state.to_preflight_dict(plans_dir=tmp_path)
        ip = next(i for i in result["in_progress"] if i["id"] == "T0.1")
        assert ip["completion_blocked_on_cd"] == ["CD.99"]

    def test_completion_blocked_on_cd_exempt_always_empty(self, tmp_path: Path) -> None:
        """bootstrap_completion_exempt=True -> completion_blocked_on_cd is [] even with pending CD."""
        items = [
            {
                **_item("T0.1", status="in_progress"),
                "related_candidate_decisions": ["CD.99"],
                "bootstrap_completion_exempt": True,
            }
        ]
        state = self._make_state(items, [_cd("CD.99")])
        result = state.to_preflight_dict(plans_dir=tmp_path)
        ip = next(i for i in result["in_progress"] if i["id"] == "T0.1")
        assert ip["completion_blocked_on_cd"] == []

    def test_completion_blocked_on_cd_no_pending_cd_empty(self, tmp_path: Path) -> None:
        """in_progress item, not exempt, but no pending gating CD -> []."""
        items = [{**_item("T0.1", status="in_progress"), "related_candidate_decisions": ["CD.99"]}]
        state = self._make_state(items, [_cd("CD.99", state="ratified")])
        result = state.to_preflight_dict(plans_dir=tmp_path)
        ip = next(i for i in result["in_progress"] if i["id"] == "T0.1")
        assert ip["completion_blocked_on_cd"] == []

    def test_completion_blocked_on_cd_gates_tier_shortcut(self, tmp_path: Path) -> None:
        """CD.gates tier shortcut gating the item's tier is surfaced in completion_blocked_on_cd."""
        items = [_item("T0.1", tier="T0", status="in_progress")]
        state = self._make_state(items, [_cd("CD.99", gates=["T0"])])
        result = state.to_preflight_dict(plans_dir=tmp_path)
        ip = next(i for i in result["in_progress"] if i["id"] == "T0.1")
        assert ip["completion_blocked_on_cd"] == ["CD.99"]

    def test_completion_blocked_on_cd_is_sorted(self, tmp_path: Path) -> None:
        """Multiple pending CDs appear in sorted (lexicographic) order."""
        items = [{**_item("T0.1", status="in_progress"), "related_candidate_decisions": ["CD.99", "CD.13"]}]
        state = self._make_state(items, [_cd("CD.99"), _cd("CD.13")])
        result = state.to_preflight_dict(plans_dir=tmp_path)
        ip = next(i for i in result["in_progress"] if i["id"] == "T0.1")
        assert ip["completion_blocked_on_cd"] == ["CD.13", "CD.99"]

    def test_completion_blocked_on_cd_decision_required_before_source(self, tmp_path: Path) -> None:
        """decision_required_before referencing a pending CD is surfaced in completion_blocked_on_cd."""
        items = [{**_item("T0.1", status="in_progress"), "decision_required_before": ["Requires CD.77"]}]
        state = self._make_state(items, [_cd("CD.77")])
        result = state.to_preflight_dict(plans_dir=tmp_path)
        ip = next(i for i in result["in_progress"] if i["id"] == "T0.1")
        assert ip["completion_blocked_on_cd"] == ["CD.77"]
