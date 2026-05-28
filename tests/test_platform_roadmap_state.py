"""Unit tests for T-1.4 additions to PlatformRoadmapState and compute_state_dict."""

from __future__ import annotations

import copy
import tempfile
from pathlib import Path

import yaml

from scripts.platform_roadmap import (
    PlatformRoadmapState,
    RoadmapDocument,
    compute_state_dict,
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
