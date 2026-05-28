"""Tests for ProductRoadmapState helpers in scripts/product_roadmap.py."""

from __future__ import annotations

import copy
from pathlib import Path

from scripts.product_roadmap import (
    ProductRoadmapDocument,
    ProductRoadmapState,
    load,
)

FIXTURES = Path(__file__).parent / "fixtures" / "product_roadmap"

_BASE_DOC: dict = {
    "document": {
        "id": "ROADMAP-PRODUCT-STATE-TEST",
        "version": 1,
        "status": "draft",
        "filed_via": "pending_log_decision_lambda",
        "gate_helpers": [],
    },
}


def _doc(**overrides) -> dict:
    d = copy.deepcopy(_BASE_DOC)
    d.update(overrides)
    return d


def _item(item_id: str, tier: str = "L1", layer: str = "alpha", status: str = "complete", **extra) -> dict:
    d = {
        "id": item_id,
        "tier": tier,
        "layer": layer,
        "name": f"State test item {item_id}",
        "depends_on": [],
        "effort": "S",
        "strategic": False,
        "status": status,
    }
    d.update(extra)
    return d


def _waiver() -> dict:
    return {"reason": "test waiver", "will_attest_when": "before status == in_progress"}


def _make_state(items: list[dict]) -> ProductRoadmapState:
    return ProductRoadmapState(ProductRoadmapDocument.model_validate(_doc(tier_items=items)))


# ---------------------------------------------------------------------------
# eligible_items and compute_blocked
# ---------------------------------------------------------------------------


class TestEligibleAndBlocked:
    def test_eligible_items_no_deps(self) -> None:
        state = _make_state(
            [
                _item("L0.1", tier="L0", status="not_started", five_property_test_waiver=_waiver()),
                _item("L0.2", tier="L0", status="not_started", five_property_test_waiver=_waiver()),
            ]
        )
        eligible_ids = {i.id for i in state.eligible_items()}
        assert eligible_ids == {"L0.1", "L0.2"}

    def test_eligible_items_with_complete_dep(self) -> None:
        state = _make_state(
            [
                _item("L0.1", tier="L0", status="complete"),
                _item("L1.1", tier="L1", status="not_started", depends_on=["L0.1"], five_property_test_waiver=_waiver()),
            ]
        )
        eligible_ids = {i.id for i in state.eligible_items()}
        assert "L1.1" in eligible_ids

    def test_eligible_items_blocked_dep_excluded(self) -> None:
        state = _make_state(
            [
                _item("L0.1", tier="L0", status="not_started", five_property_test_waiver=_waiver()),
                _item("L1.1", tier="L1", status="not_started", depends_on=["L0.1"], five_property_test_waiver=_waiver()),
            ]
        )
        eligible_ids = {i.id for i in state.eligible_items()}
        assert "L1.1" not in eligible_ids

    def test_compute_blocked_with_incomplete_dep(self) -> None:
        state = _make_state(
            [
                _item("L0.1", tier="L0", status="not_started", five_property_test_waiver=_waiver()),
                _item("L1.1", tier="L1", status="not_started", depends_on=["L0.1"], five_property_test_waiver=_waiver()),
            ]
        )
        blocked_ids = {i.id for i in state.compute_blocked()}
        assert "L1.1" in blocked_ids

    def test_in_progress_items(self) -> None:
        state = _make_state(
            [
                _item("L0.1", tier="L0", status="in_progress", five_property_test_waiver=_waiver()),
                _item("L0.2", tier="L0", status="not_started", five_property_test_waiver=_waiver()),
            ]
        )
        ip = {i.id for i in state.in_progress_items()}
        assert ip == {"L0.1"}


# ---------------------------------------------------------------------------
# layer_complete
# ---------------------------------------------------------------------------


class TestLayerComplete:
    def test_all_done_passes(self) -> None:
        state = _make_state(
            [
                _item("L0.1", tier="L0", status="complete"),
                _item("L0.2", tier="L0", status="complete"),
            ]
        )
        assert state.layer_complete("L0") is True

    def test_any_incomplete_fails(self) -> None:
        state = _make_state(
            [
                _item("L0.1", tier="L0", status="complete"),
                _item("L0.2", tier="L0", status="not_started", five_property_test_waiver=_waiver()),
            ]
        )
        assert state.layer_complete("L0") is False

    def test_reserved_excluded_from_layer_complete(self) -> None:
        state = _make_state(
            [
                _item("L0.1", tier="L0", status="complete"),
                {**_item("L0.2", tier="L0"), "status": "reserved", "five_property_test_waiver": _waiver()},
            ]
        )
        assert state.layer_complete("L0") is True

    def test_aggregate_d_complete_requires_both_sublayers(self) -> None:
        state = _make_state(
            [
                _item("D.fast.1", tier="D.fast", status="complete"),
                _item("D.lake.1", tier="D.lake", status="not_started", five_property_test_waiver=_waiver()),
            ]
        )
        assert state.layer_complete("D") is False

    def test_aggregate_d_complete_when_both_done(self) -> None:
        state = _make_state(
            [
                _item("D.fast.1", tier="D.fast", status="complete"),
                _item("D.lake.1", tier="D.lake", status="complete"),
            ]
        )
        assert state.layer_complete("D") is True


# ---------------------------------------------------------------------------
# active_layer
# ---------------------------------------------------------------------------


class TestActiveLayer:
    def test_active_layer_canonical_order(self) -> None:
        # L0 incomplete -> active_layer returns L0 (first in canonical order)
        state = _make_state(
            [
                _item("L0.1", tier="L0", status="not_started", five_property_test_waiver=_waiver()),
                _item("L1.1", tier="L1", status="not_started", five_property_test_waiver=_waiver()),
            ]
        )
        assert state.active_layer() == "L0"

    def test_active_layer_advances_when_l0_complete(self) -> None:
        state = _make_state(
            [
                _item("L0.1", tier="L0", status="complete"),
                _item("L1.1", tier="L1", status="not_started", five_property_test_waiver=_waiver()),
            ]
        )
        assert state.active_layer() == "L1"

    def test_active_layer_none_when_all_complete(self) -> None:
        state = _make_state(
            [
                _item("L0.1", tier="L0", status="complete"),
            ]
        )
        assert state.active_layer() is None


# ---------------------------------------------------------------------------
# strategic_pending_items
# ---------------------------------------------------------------------------


class TestStrategicPending:
    def test_strategic_items_isolated(self) -> None:
        state = _make_state(
            [
                _item("L0.1", tier="L0", status="not_started", strategic=True, five_property_test_waiver=_waiver()),
                _item("L0.2", tier="L0", status="not_started", strategic=False, five_property_test_waiver=_waiver()),
            ]
        )
        strategic_ids = {i.id for i in state.strategic_pending_items()}
        eligible_ids = {i.id for i in state.eligible_items()}
        assert strategic_ids == {"L0.1"}
        assert "L0.1" in eligible_ids  # eligible_items includes strategic items
        assert "L0.2" in eligible_ids


# ---------------------------------------------------------------------------
# resolve_depends_on
# ---------------------------------------------------------------------------


class TestResolveDependsOn:
    def test_direct_dep(self) -> None:
        state = _make_state(
            [
                _item("L0.1", tier="L0"),
                _item("L1.1", tier="L1", depends_on=["L0.1"]),
            ]
        )
        deps = state.resolve_depends_on("L1.1")
        assert len(deps) == 1
        assert deps[0].id == "L0.1"

    def test_layer_shortcut(self) -> None:
        state = _make_state(
            [
                _item("L0.1", tier="L0"),
                _item("L0.2", tier="L0"),
                _item("L1.1", tier="L1", depends_on=["L0"]),
            ]
        )
        dep_ids = {d.id for d in state.resolve_depends_on("L1.1")}
        assert dep_ids == {"L0.1", "L0.2"}

    def test_aggregate_shortcut_d_expands(self) -> None:
        state = _make_state(
            [
                _item("D.fast.1", tier="D.fast", status="complete"),
                _item("D.lake.1", tier="D.lake", status="complete"),
                _item("E.env.1", tier="E.env", status="not_started", depends_on=["D"], five_property_test_waiver=_waiver()),
            ]
        )
        dep_ids = {d.id for d in state.resolve_depends_on("E.env.1")}
        assert dep_ids == {"D.fast.1", "D.lake.1"}

    def test_nonexistent_item_returns_empty(self) -> None:
        state = _make_state([_item("L0.1", tier="L0")])
        assert state.resolve_depends_on("NONEXISTENT") == []


# ---------------------------------------------------------------------------
# platform_consumers maps
# ---------------------------------------------------------------------------


class TestPlatformConsumers:
    @classmethod
    def _state_from_fixture(cls) -> ProductRoadmapState:
        doc = load(
            FIXTURES / "minimal_product.yaml",
            platform_path=FIXTURES / "minimal_platform.yaml",
        )
        return ProductRoadmapState(doc)

    def test_platform_tier_item_consumers_correct(self) -> None:
        state = self._state_from_fixture()
        consumers = state.platform_tier_item_consumers()
        assert consumers.get("T-1.5") == ["L0.1"]
        assert consumers.get("T0.1") == ["D.fast.1", "L1.alpha.1"]
        assert consumers.get("T0.2") == ["L2.portfolio.1"]

    def test_platform_gap_consumers_correct(self) -> None:
        state = self._state_from_fixture()
        assert state.platform_gap_consumers().get("GAP-fixture-gap") == ["L1.alpha.1"]

    def test_platform_cd_consumers_correct(self) -> None:
        state = self._state_from_fixture()
        assert state.platform_cd_consumers().get("CD.1") == ["L1.alpha.1"]

    def test_empty_consumers_when_no_cross_refs(self) -> None:
        state = _make_state([_item("L0.1", tier="L0", status="complete")])
        assert state.platform_tier_item_consumers() == {}
        assert state.platform_gap_consumers() == {}
        assert state.platform_cd_consumers() == {}

    def test_consumers_values_are_sorted(self) -> None:
        # Two items both referencing the same PLATFORM tier_item -> sorted order
        items = [
            {**_item("L1.1", tier="L1", status="complete"), "cross_roadmap_depends_on": ["PLATFORM:T0.1"]},
            {**_item("L0.1", tier="L0", status="complete"), "cross_roadmap_depends_on": ["PLATFORM:T0.1"]},
        ]
        state = _make_state(items)
        consumers = state.platform_tier_item_consumers()
        assert consumers["T0.1"] == sorted(consumers["T0.1"])
