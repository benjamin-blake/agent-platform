"""Tests for scripts/platform_roadmap_state.py: loader, eligibility/blocking, CD-gating, follow-on state."""

from __future__ import annotations

import copy
import tempfile
from pathlib import Path

import pytest
import yaml

from scripts.roadmap.platform_roadmap import (
    PlatformRoadmapState,
    RoadmapDocument,
    compute_followon_state,
    compute_state_dict,
    load,
)

# ---------------------------------------------------------------------------
# Shared fixture helpers (mirrors pattern in test_platform_roadmap.py)
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


def _item(
    item_id: str,
    tier: str = "T0",
    depends_on: list | None = None,
    status: str = "not_started",
    strategic: bool = False,
) -> dict:
    return {
        "id": item_id,
        "tier": tier,
        "name": f"Test item {item_id}",
        "depends_on": depends_on or [],
        "files_in_scope": [],
        "exit_criteria": [],
        "effort": "S",
        "strategic": strategic,
        "status": status,
    }


def _make_state(items: list[dict]) -> PlatformRoadmapState:
    doc = RoadmapDocument.model_validate(_doc(tier_items=items))
    return PlatformRoadmapState(doc)


def _write_fixture_yaml(items: list[dict]) -> Path:
    """Write a minimal valid roadmap YAML to a temp file and return its path."""
    data = _doc(tier_items=items)
    tmp = tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False, encoding="utf-8")
    yaml.dump(data, tmp)
    tmp.close()
    return Path(tmp.name)


def _cd(cd_id: str, state: str = "pending", gates: list | None = None, realization_evidence: str | None = None) -> dict:
    d = {"id": cd_id, "title": f"Decision {cd_id}", "state": state, "gates": gates or []}
    if realization_evidence is not None:
        d["realization_evidence"] = realization_evidence
    return d


def _state_from_doc(doc_dict: dict) -> PlatformRoadmapState:
    return PlatformRoadmapState(RoadmapDocument.model_validate(doc_dict))


_LIVE_ROADMAP = Path(__file__).parent.parent / "docs" / "ROADMAP-PLATFORM.yaml"


# ---------------------------------------------------------------------------
# test_eligible_items
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
# test_compute_blocked
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
# test_strategic_pending
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
# test_tier_shortcut_resolution
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
# test_active_tier
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
# test_stale_cache_note
# ---------------------------------------------------------------------------


class TestStaleCacheNote:
    def _write_yaml(self, items: list | None = None) -> Path:
        return _write_fixture_yaml(items or [_item("T0.1")])

    def test_stale_cache_note_present_when_yaml_newer(self) -> None:
        path = self._write_yaml()
        try:
            # A decision timestamp far in the past -- YAML mtime will be newer
            result = compute_state_dict(path, latest_decision_ts="2020-01-01T00:00:00+00:00")
            assert "stale_cache_note" in result, f"expected stale_cache_note; got keys: {list(result)}"
            assert "roadmap edits awaiting ratification" in result["stale_cache_note"]
        finally:
            path.unlink(missing_ok=True)

    def test_stale_cache_note_absent_when_decision_newer(self) -> None:
        path = self._write_yaml()
        try:
            # A decision timestamp far in the future -- YAML mtime will be older
            result = compute_state_dict(path, latest_decision_ts="2099-01-01T00:00:00+00:00")
            assert "stale_cache_note" not in result, f"unexpected stale_cache_note: {result.get('stale_cache_note')}"
        finally:
            path.unlink(missing_ok=True)

    def test_stale_cache_note_absent_when_ts_none(self) -> None:
        path = self._write_yaml()
        try:
            result = compute_state_dict(path, latest_decision_ts=None)
            assert "stale_cache_note" not in result
        finally:
            path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# test_compute_state_dict (error branch + shape)
# ---------------------------------------------------------------------------


class TestComputeStateDict:
    def test_error_on_missing_file(self) -> None:
        result = compute_state_dict(Path("/nonexistent/ROADMAP.yaml"))
        assert "error" in result
        assert result["next_eligible"] == []
        assert result["in_progress"] == []
        assert result["blocked"] == []
        assert result["strategic_pending"] == []
        assert result["active_tier"] is None

    def test_error_on_bad_yaml(self) -> None:
        tmp = tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False, encoding="utf-8")
        tmp.write(":: bad: : :\n")
        tmp.close()
        try:
            result = compute_state_dict(Path(tmp.name))
            assert "error" in result
        finally:
            Path(tmp.name).unlink(missing_ok=True)

    def test_shape_on_valid_yaml(self) -> None:
        path = _write_fixture_yaml([_item("T0.1"), _item("T0.2", depends_on=["T0.1"])])
        try:
            result = compute_state_dict(path)
            for key in ("next_eligible", "in_progress", "blocked", "strategic_pending", "active_tier"):
                assert key in result, f"missing key: {key}"
        finally:
            path.unlink(missing_ok=True)

    def test_item_shape_has_required_fields(self) -> None:
        path = _write_fixture_yaml([_item("T0.1")])
        try:
            result = compute_state_dict(path)
            assert result["next_eligible"]
            item = result["next_eligible"][0]
            for field in ("id", "tier", "name", "effort", "strategic"):
                assert field in item, f"missing field: {field}"
        finally:
            path.unlink(missing_ok=True)

    def test_blocked_item_has_blocked_on_field(self) -> None:
        path = _write_fixture_yaml(
            [
                _item("T0.dep"),
                _item("T0.blocked", depends_on=["T0.dep"]),
            ]
        )
        try:
            result = compute_state_dict(path)
            assert result["blocked"]
            blocked_item = result["blocked"][0]
            assert "blocked_on" in blocked_item
            assert blocked_item["blocked_on"] == ["T0.dep"]
        finally:
            path.unlink(missing_ok=True)


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
# TestRatifiableCds -- candidate-decision-ratification lane surfacing
# ---------------------------------------------------------------------------


class TestRatifiableCds:
    def test_defaults_to_none_and_excluded(self) -> None:
        doc = _doc(candidate_decisions=[_cd("CD.1")])
        result = _state_from_doc(doc).ratifiable_cds()
        assert result == []

    def test_pending_with_evidence_included(self) -> None:
        doc = _doc(candidate_decisions=[_cd("CD.6", realization_evidence="Realized 2026-05-28: ...")])
        result = _state_from_doc(doc).ratifiable_cds()
        assert len(result) == 1
        assert result[0]["id"] == "CD.6"
        assert result[0]["realization_evidence"] == "Realized 2026-05-28: ..."

    def test_ratified_with_evidence_excluded(self) -> None:
        doc = _doc(candidate_decisions=[_cd("CD.36", state="ratified", realization_evidence="already ratified")])
        result = _state_from_doc(doc).ratifiable_cds()
        assert result == []

    def test_pending_without_evidence_excluded(self) -> None:
        doc = _doc(candidate_decisions=[_cd("CD.29")])
        result = _state_from_doc(doc).ratifiable_cds()
        assert result == []

    def test_present_in_to_preflight_dict(self) -> None:
        doc = _doc(candidate_decisions=[_cd("CD.6", realization_evidence="Realized")])
        full = _state_from_doc(doc).to_preflight_dict()
        assert "ratifiable_cds" in full
        assert [c["id"] for c in full["ratifiable_cds"]] == ["CD.6"]


# ---------------------------------------------------------------------------
# TestRealizedButPendingCds -- close-audit-ulf-02: prose-'[Realized' corroboration signal,
# kept distinct from the deliberate realization_evidence-keyed ratifiable_cds()
# ---------------------------------------------------------------------------


class TestRealizedButPendingCds:
    def test_pending_with_realized_marker_and_no_evidence_surfaced(self) -> None:
        doc = _doc(
            candidate_decisions=[
                {**_cd("CD.2"), "detail": "Some prose. [Realized 2026-05-30: CC-web dev surface operational."}
            ]
        )
        result = _state_from_doc(doc).realized_but_pending_cds()
        assert len(result) == 1
        assert result[0]["id"] == "CD.2"
        assert result[0]["realized_hint"].startswith("[Realized")

    def test_pending_with_evidence_excluded_belongs_to_ratifiable(self) -> None:
        doc = _doc(
            candidate_decisions=[
                {
                    **_cd("CD.6", realization_evidence="Realized 2026-05-28: ..."),
                    "detail": "[Realized 2026-05-28: shipped.",
                }
            ]
        )
        result = _state_from_doc(doc).realized_but_pending_cds()
        assert result == []

    def test_pending_without_marker_excluded(self) -> None:
        doc = _doc(candidate_decisions=[{**_cd("CD.1"), "detail": "Plain detail, no marker."}])
        result = _state_from_doc(doc).realized_but_pending_cds()
        assert result == []

    def test_ratified_with_marker_excluded(self) -> None:
        doc = _doc(candidate_decisions=[{**_cd("CD.99", state="ratified"), "detail": "[Realized 2026-01-01: done."}])
        result = _state_from_doc(doc).realized_but_pending_cds()
        assert result == []

    def test_present_in_to_preflight_dict(self) -> None:
        doc = _doc(candidate_decisions=[{**_cd("CD.2"), "detail": "[Realized 2026-05-30: shipped."}])
        full = _state_from_doc(doc).to_preflight_dict()
        assert "realized_but_pending_cds" in full
        assert [c["id"] for c in full["realized_but_pending_cds"]] == ["CD.2"]


# ---------------------------------------------------------------------------
# TestLiveGateEvaluations -- T-1.20 live-YAML anchors
# ---------------------------------------------------------------------------


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

    def test_plans_dir_default_is_absolute_repo_anchored(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Default plans_dir resolves to repo-anchored absolute path, not CWD-relative (rec-2349)."""
        import inspect

        src = inspect.getsource(PlatformRoadmapState.to_preflight_dict)
        assert 'Path("docs/plans")' not in src, "Default plans_dir must not be CWD-relative string literal"

        # Behavioral: from a different CWD the default must still reach the real plans dir.
        roadmap = Path(__file__).parent.parent / "docs" / "ROADMAP-PLATFORM.yaml"
        doc = load(roadmap)
        state = PlatformRoadmapState(doc)

        real_plans_dir = Path(__file__).parent.parent / "docs" / "plans"
        baseline = state.to_preflight_dict(plans_dir=real_plans_dir)

        monkeypatch.chdir(tmp_path)
        default = state.to_preflight_dict()

        baseline_map = {i["id"]: i for i in baseline["in_progress"]}
        for item in default["in_progress"]:
            if item["id"] in baseline_map:
                assert item["needs_followon_plan"] == baseline_map[item["id"]]["needs_followon_plan"], (
                    f"{item['id']}: default plans_dir produced different needs_followon_plan than explicit absolute path"
                )

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


# ---------------------------------------------------------------------------
# TestComputeFollowonStateMalformedPlanShapes -- closes coverage gaps in the
# per-plan-file skip branches of compute_followon_state. Distinct from
# test_malformed_plan_skipped above (which exercises the OUTER yaml.safe_load
# exception path, e.g. genuine YAML syntax errors): these exercise
# successfully-PARSED-but-wrong-shaped YAML, which the outer except never sees.
# ---------------------------------------------------------------------------


class TestComputeFollowonStateMalformedPlanShapes:
    def _make_doc(self, items: list[dict]) -> RoadmapDocument:
        d = copy.deepcopy(_BASE_DOC)
        d["tier_items"] = items
        return RoadmapDocument.model_validate(d)

    def _in_progress_item(self, item_id: str, criteria: list[dict]) -> dict:
        item = _item(item_id, status="in_progress")
        item["exit_criteria"] = criteria
        return item

    def test_plan_yaml_top_level_not_dict_skipped(self, tmp_path: Path) -> None:
        # Valid YAML that parses to a list (not a dict) at the top level.
        doc = self._make_doc([self._in_progress_item("A", [{"id": "c1", "text": "x", "status": "open"}])])
        (tmp_path / "PLAN-list-toplevel.yaml").write_text("- a\n- b\n")
        result = compute_followon_state(doc, tmp_path)
        assert result["A"]["needs_followon_plan"] is True

    def test_closes_criteria_not_a_list_skipped(self, tmp_path: Path) -> None:
        # closes_criteria present but not list-shaped (a bare scalar string).
        doc = self._make_doc([self._in_progress_item("A", [{"id": "c1", "text": "x", "status": "open"}])])
        (tmp_path / "PLAN-bad-closes.yaml").write_text("closes_criteria: not-a-list-value\n")
        result = compute_followon_state(doc, tmp_path)
        assert result["A"]["needs_followon_plan"] is True

    def test_closes_criteria_entry_malformed_skipped(self, tmp_path: Path) -> None:
        # One entry is a non-str (int); the other is a str missing the
        # required ':' item_id/crit_id separator. Both hit the same continue.
        doc = self._make_doc([self._in_progress_item("A", [{"id": "c1", "text": "x", "status": "open"}])])
        (tmp_path / "PLAN-bad-entries.yaml").write_text("closes_criteria:\n  - 123\n  - malformed-ref-without-colon\n")
        result = compute_followon_state(doc, tmp_path)
        assert result["A"]["needs_followon_plan"] is True


# ---------------------------------------------------------------------------
# TestComputeStateDictDecisionTsEdgeCases -- closes coverage gaps in the
# latest_decision_ts branch of compute_state_dict: naive-datetime tzinfo
# backfill, and the outer except-guard for a wholly unparseable timestamp.
# Distinct from TestStaleCacheNote above, whose fixtures always pass an
# explicit UTC offset ("+00:00"), so decision_dt.tzinfo is never None there.
# ---------------------------------------------------------------------------


class TestComputeStateDictDecisionTsEdgeCases:
    def _write_yaml(self) -> Path:
        return _write_fixture_yaml([_item("T0.1")])

    def test_naive_decision_ts_backfilled_to_utc(self) -> None:
        path = self._write_yaml()
        try:
            # No UTC offset -- datetime.fromisoformat produces a naive datetime,
            # exercising the tzinfo-is-None backfill branch before comparison.
            result = compute_state_dict(path, latest_decision_ts="2020-01-01T00:00:00")
            assert "stale_cache_note" in result, f"expected stale_cache_note; got keys: {list(result)}"
        finally:
            path.unlink(missing_ok=True)

    def test_invalid_decision_ts_format_silently_ignored(self) -> None:
        path = self._write_yaml()
        try:
            # Not parseable by datetime.fromisoformat at all -- caught by the
            # outer except-guard; function must not raise and must omit the note.
            result = compute_state_dict(path, latest_decision_ts="not-a-real-timestamp")
            assert "stale_cache_note" not in result
        finally:
            path.unlink(missing_ok=True)


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
