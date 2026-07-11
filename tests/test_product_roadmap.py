"""Tests for scripts/roadmap/product_roadmap.py covering schema validation, graph checks, and cross-roadmap resolution."""

from __future__ import annotations

import copy
import tempfile
from pathlib import Path

import pytest

from scripts.roadmap.platform_roadmap import RoadmapDocument as PlatformDoc
from scripts.roadmap.product_roadmap import (
    GateRuleParser,
    ProductRoadmapDocument,
    load,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures" / "product_roadmap"

_BASE_DOC: dict = {
    "document": {
        "id": "ROADMAP-PRODUCT-TEST",
        "version": 1,
        "status": "draft",
        "filed_via": "pending_log_decision_lambda",
        "gate_helpers": [
            {"name": "deflated_sharpe", "arity": 3, "scope": "product_local"},
        ],
    },
}


def _doc(**overrides) -> dict:
    d = copy.deepcopy(_BASE_DOC)
    d.update(overrides)
    return d


def _item(
    item_id: str,
    tier: str = "L1",
    layer: str = "alpha",
    depends_on: list | None = None,
    status: str = "complete",
    **extra,
) -> dict:
    d = {
        "id": item_id,
        "tier": tier,
        "layer": layer,
        "name": f"Test item {item_id}",
        "depends_on": depends_on or [],
        "effort": "S",
        "strategic": False,
        "status": status,
    }
    d.update(extra)
    return d


def _waiver(**kw) -> dict:
    base = {"reason": "test waiver reason", "will_attest_when": "before status == in_progress"}
    base.update(kw)
    return base


def _fpt() -> dict:
    return {
        "parameterised": {"attestation": "x", "cites": "y"},
        "versioned": {"attestation": "x", "cites": "y"},
        "composable": {"attestation": "x", "cites": "y"},
        "observable": {"attestation": "x", "cites": "y"},
        "evaluable": {"attestation": "x", "cites": "y"},
    }


def _platform_item(item_id: str, tier: str = "T0", status: str = "not_started") -> dict:
    return {
        "id": item_id,
        "tier": tier,
        "name": f"Platform {item_id}",
        "depends_on": [],
        "files_in_scope": [],
        "exit_criteria": [],
        "effort": "S",
        "strategic": False,
        "status": status,
    }


def _platform_doc(tier_items: list | None = None, cds: list | None = None) -> PlatformDoc:
    data = {
        "document": {
            "id": "ROADMAP-PLATFORM-TEST",
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
        "tier_items": tier_items or [],
        "candidate_decisions": cds or [],
        "cross_tier_gates": [],
    }
    return PlatformDoc.model_validate(data)


# ---------------------------------------------------------------------------
# TestLoad
# ---------------------------------------------------------------------------


class TestLoad:
    def test_loads_live_yaml(self) -> None:
        roadmap = Path(__file__).parent.parent / "docs" / "ROADMAP-PRODUCT.yaml"
        platform = Path(__file__).parent.parent / "docs" / "ROADMAP-PLATFORM.yaml"
        doc = load(roadmap, platform_path=platform)
        assert len(doc.tier_items) >= 70
        assert len(doc.known_platform_gaps) == 6

    def test_missing_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load("/nonexistent/path/ROADMAP.yaml")

    def test_invalid_yaml_raises(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False, encoding="utf-8") as f:
            f.write(":: not valid yaml: [[[")
            tmp = f.name
        try:
            with pytest.raises(Exception):
                load(tmp)
        finally:
            Path(tmp).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# TestStructuralValidation
# ---------------------------------------------------------------------------


class TestStructuralValidation:
    def test_tier_items_wrong_type_raises(self) -> None:
        with pytest.raises(Exception):
            ProductRoadmapDocument.model_validate(_doc(tier_items="not-a-list"))

    def test_missing_document_raises(self) -> None:
        with pytest.raises(Exception):
            ProductRoadmapDocument.model_validate({"tier_items": []})

    def test_valid_minimal_doc_passes(self) -> None:
        doc = ProductRoadmapDocument.model_validate(_BASE_DOC)
        assert doc.document.id == "ROADMAP-PRODUCT-TEST"

    def test_unsupported_version_raises(self) -> None:
        d = copy.deepcopy(_BASE_DOC)
        d["document"]["version"] = 99
        with pytest.raises(Exception, match="Unsupported"):
            ProductRoadmapDocument.model_validate(d)


# ---------------------------------------------------------------------------
# TestIdUniqueness
# ---------------------------------------------------------------------------


class TestIdUniqueness:
    def test_duplicate_tier_item_id_raises(self) -> None:
        d = _doc(tier_items=[_item("L1.1"), _item("L1.1")])
        with pytest.raises(Exception, match="[Dd]uplicate"):
            ProductRoadmapDocument.model_validate(d)

    def test_duplicate_candidate_decision_id_raises(self) -> None:
        d = _doc(
            tier_items=[_item("L1.1")],
            candidate_decisions=[
                {"id": "CDP.1", "title": "A", "gates": []},
                {"id": "CDP.1", "title": "B", "gates": []},
            ],
        )
        with pytest.raises(Exception, match="[Dd]uplicate"):
            ProductRoadmapDocument.model_validate(d)

    def test_duplicate_known_platform_gap_id_raises(self) -> None:
        d = _doc(
            known_platform_gaps=[
                {"id": "GAP-test", "description": "a", "intended_platform_tier_item": "pending_triage"},
                {"id": "GAP-test", "description": "b", "intended_platform_tier_item": "pending_triage"},
            ],
        )
        with pytest.raises(Exception, match="[Dd]uplicate"):
            ProductRoadmapDocument.model_validate(d)

    def test_unique_ids_pass(self) -> None:
        d = _doc(tier_items=[_item("L1.1"), _item("L1.2")])
        doc = ProductRoadmapDocument.model_validate(d)
        assert len(doc.tier_items) == 2


# ---------------------------------------------------------------------------
# TestDanglingDependsOn
# ---------------------------------------------------------------------------


class TestDanglingDependsOn:
    def test_nonexistent_dep_raises(self) -> None:
        d = _doc(tier_items=[_item("L1.1", depends_on=["L9.999"])])
        with pytest.raises(Exception, match="does not resolve"):
            ProductRoadmapDocument.model_validate(d)

    def test_valid_dep_passes(self) -> None:
        d = _doc(tier_items=[_item("L0.1", tier="L0"), _item("L1.1", tier="L1", depends_on=["L0.1"])])
        doc = ProductRoadmapDocument.model_validate(d)
        assert doc.tier_items[1].depends_on == ["L0.1"]

    def test_layer_shortcut_dep_passes(self) -> None:
        d = _doc(
            tier_items=[
                _item("L0.1", tier="L0"),
                _item("L1.1", tier="L1", depends_on=["L0"]),
            ]
        )
        doc = ProductRoadmapDocument.model_validate(d)
        assert "L0" in doc.tier_items[1].depends_on


# ---------------------------------------------------------------------------
# TestCycleDetection
# ---------------------------------------------------------------------------


class TestCycleDetection:
    def test_direct_cycle_raises(self) -> None:
        d = _doc(
            tier_items=[
                _item("L0.1", tier="L0", depends_on=["L0.2"]),
                _item("L0.2", tier="L0", depends_on=["L0.1"]),
            ]
        )
        with pytest.raises(Exception, match="[Cc]ycle"):
            ProductRoadmapDocument.model_validate(d)

    def test_three_node_cycle_raises(self) -> None:
        d = _doc(
            tier_items=[
                _item("L0.1", tier="L0", depends_on=["L0.3"]),
                _item("L0.2", tier="L0", depends_on=["L0.1"]),
                _item("L0.3", tier="L0", depends_on=["L0.2"]),
            ]
        )
        with pytest.raises(Exception, match="[Cc]ycle"):
            ProductRoadmapDocument.model_validate(d)

    def test_linear_chain_passes(self) -> None:
        d = _doc(
            tier_items=[
                _item("L0.1", tier="L0"),
                _item("L1.1", tier="L1", depends_on=["L0.1"]),
                _item("L2.1", tier="L2", depends_on=["L1.1"]),
            ]
        )
        doc = ProductRoadmapDocument.model_validate(d)
        assert len(doc.tier_items) == 3

    def test_layer_shortcut_cycle_raises(self) -> None:
        # L0 depends on L1 and L1 depends on L0 via layer shortcuts -> cycle
        d = _doc(
            tier_items=[
                _item("L0.1", tier="L0", depends_on=["L1"]),
                _item("L1.1", tier="L1", depends_on=["L0"]),
            ]
        )
        with pytest.raises(Exception, match="[Cc]ycle"):
            ProductRoadmapDocument.model_validate(d)

    def test_aggregate_shortcut_cycle_raises(self) -> None:
        # D.fast.1 depends on D.lake shortcut; D.lake.1 depends on D.fast shortcut -> cycle
        d = _doc(
            tier_items=[
                _item("D.fast.1", tier="D.fast", depends_on=["D.lake"], five_property_test_waiver=_waiver()),
                _item("D.lake.1", tier="D.lake", depends_on=["D.fast"], five_property_test_waiver=_waiver()),
            ]
        )
        with pytest.raises(Exception, match="[Cc]ycle"):
            ProductRoadmapDocument.model_validate(d)


# ---------------------------------------------------------------------------
# TestGateRuleGrammar
# ---------------------------------------------------------------------------


_PRODUCT_HELPERS: dict[str, int] = {"deflated_sharpe": 3}
_PLATFORM_HELPERS: dict[str, int] = {"tier_complete": 1, "item_field_eq": 3}
_ALL_HELPERS: dict[str, int] = {**_PLATFORM_HELPERS, **_PRODUCT_HELPERS}


class TestGateRuleGrammar:
    def test_unknown_helper_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown"):
            GateRuleParser.validate("bogus_helper(L1.1)", _PRODUCT_HELPERS)

    def test_arity_mismatch_product_local_raises(self) -> None:
        with pytest.raises(ValueError, match="expected 3"):
            GateRuleParser.validate("deflated_sharpe(L1)", _PRODUCT_HELPERS)

    def test_arity_mismatch_inherited_raises(self) -> None:
        with pytest.raises(ValueError, match="expected 1"):
            GateRuleParser.validate('tier_complete("L0", "L1")', _ALL_HELPERS)

    def test_product_local_helper_passes(self) -> None:
        GateRuleParser.validate('deflated_sharpe("L1", "sharpe", "2.0")', _PRODUCT_HELPERS)

    def test_inherited_platform_helper_passes(self) -> None:
        GateRuleParser.validate('tier_complete("L0")', _ALL_HELPERS)

    def test_combined_rule_passes(self) -> None:
        rule = 'tier_complete("L0") and deflated_sharpe("L1", "sharpe", "1.5")'
        GateRuleParser.validate(rule, _ALL_HELPERS)

    def test_gate_rule_rejected_in_model(self) -> None:
        d = _doc(cross_tier_gates=[{"id": "G.X", "name": "Test", "rule": "bogus_helper(L1.1)", "rationale": "test"}])
        with pytest.raises(Exception, match="Unknown"):
            ProductRoadmapDocument.model_validate(d)

    def test_valid_gate_rule_in_model_product_local_helper(self) -> None:
        d = _doc(
            tier_items=[_item("L1.1", tier="L1")],
            cross_tier_gates=[
                {"id": "G.X", "name": "Test", "rule": 'deflated_sharpe("L1", "sharpe", "2.0")', "rationale": "test"}
            ],
        )
        doc = ProductRoadmapDocument.model_validate(d)
        assert doc.cross_tier_gates[0].id == "G.X"

    def test_cd_decision_required_before_bad_helper_raises(self) -> None:
        d = _doc(
            tier_items=[_item("L1.1", tier="L1")],
            candidate_decisions=[{"id": "CDP.X", "title": "T", "gates": [], "decision_required_before": "bogus_helper(L1.1)"}],
        )
        with pytest.raises(Exception, match="Unknown"):
            ProductRoadmapDocument.model_validate(d)


# ---------------------------------------------------------------------------
# TestCrossRoadmapResolution
# ---------------------------------------------------------------------------


class TestCrossRoadmapResolution:
    def _plat(self) -> PlatformDoc:
        return _platform_doc(
            tier_items=[
                _platform_item("T0.1"),
                _platform_item("T1.8", tier="T1", status="reserved"),
            ],
            cds=[{"id": "CD.1", "title": "CD 1", "gates": []}],
        )

    def _product_item_with_ref(self, ref: str, gap_id: str | None = None) -> dict:
        d = _doc(
            tier_items=[
                _item(
                    "L1.1",
                    status="complete",
                    cross_roadmap_depends_on=[ref],
                )
            ],
        )
        if gap_id:
            d["known_platform_gaps"] = [{"id": gap_id, "description": "test", "intended_platform_tier_item": "pending_triage"}]
        return d

    def test_dangling_platform_tier_item_raises(self) -> None:
        plat = self._plat()
        d = self._product_item_with_ref("PLATFORM:T999.0")
        with pytest.raises(Exception, match="does not resolve"):
            ProductRoadmapDocument.model_validate(d, context={"platform_doc": plat})

    def test_dangling_platform_cd_raises(self) -> None:
        plat = self._plat()
        d = self._product_item_with_ref("PLATFORM:CD.999")
        with pytest.raises(Exception):
            ProductRoadmapDocument.model_validate(d, context={"platform_doc": plat})

    def test_unregistered_gap_raises(self) -> None:
        plat = self._plat()
        d = self._product_item_with_ref("PLATFORM:GAP-unregistered")
        with pytest.raises(Exception, match="not registered"):
            ProductRoadmapDocument.model_validate(d, context={"platform_doc": plat})

    def test_valid_platform_tier_item_passes(self) -> None:
        plat = self._plat()
        d = self._product_item_with_ref("PLATFORM:T0.1")
        doc = ProductRoadmapDocument.model_validate(d, context={"platform_doc": plat})
        assert doc.tier_items[0].cross_roadmap_depends_on == ["PLATFORM:T0.1"]

    def test_valid_platform_gap_passes(self) -> None:
        plat = self._plat()
        d = self._product_item_with_ref("PLATFORM:GAP-test-gap", gap_id="GAP-test-gap")
        doc = ProductRoadmapDocument.model_validate(d, context={"platform_doc": plat})
        assert any("GAP-test-gap" in ref for ref in doc.tier_items[0].cross_roadmap_depends_on)

    def test_valid_platform_cd_passes(self) -> None:
        plat = self._plat()
        d = self._product_item_with_ref("PLATFORM:CD.1")
        doc = ProductRoadmapDocument.model_validate(d, context={"platform_doc": plat})
        assert doc.tier_items[0].cross_roadmap_depends_on == ["PLATFORM:CD.1"]

    def test_reserved_platform_item_raises(self) -> None:
        plat = self._plat()
        d = self._product_item_with_ref("PLATFORM:T1.8")
        with pytest.raises(Exception, match="restricted"):
            ProductRoadmapDocument.model_validate(d, context={"platform_doc": plat})

    def test_cross_roadmap_validation_skipped_without_platform_doc(self) -> None:
        # Dangling PLATFORM ref should NOT raise when platform_doc is absent -- only a warning
        d = self._product_item_with_ref("PLATFORM:T999.0")
        doc = ProductRoadmapDocument.model_validate(d)  # no context
        assert len(doc.tier_items) == 1


# ---------------------------------------------------------------------------
# TestFivePropertyEnforcement
# ---------------------------------------------------------------------------


class TestFivePropertyEnforcement:
    def test_complete_status_any_layer_exempt_platform_infra(self) -> None:
        d = _doc(tier_items=[_item("L0.1", tier="L0", layer="platform_infra", status="complete")])
        doc = ProductRoadmapDocument.model_validate(d)
        assert doc.tier_items[0].five_property_test is None

    def test_complete_status_any_layer_exempt_lab_offline(self) -> None:
        # Broadened exemption rule: lab_offline layer also exempt when complete
        d = _doc(tier_items=[_item("L0.5", tier="L0", layer="lab_offline", status="complete")])
        doc = ProductRoadmapDocument.model_validate(d)
        assert doc.tier_items[0].five_property_test is None

    def test_not_started_without_fpt_or_waiver_raises(self) -> None:
        d = _doc(tier_items=[_item("L1.1", tier="L1", status="not_started")])
        with pytest.raises(Exception, match="five_property_test"):
            ProductRoadmapDocument.model_validate(d)

    def test_not_started_with_valid_fpt_passes(self) -> None:
        d = _doc(tier_items=[_item("L1.1", tier="L1", status="not_started", five_property_test=_fpt())])
        doc = ProductRoadmapDocument.model_validate(d)
        assert doc.tier_items[0].five_property_test is not None

    def test_not_started_with_valid_waiver_passes(self) -> None:
        d = _doc(tier_items=[_item("L1.1", tier="L1", status="not_started", five_property_test_waiver=_waiver())])
        doc = ProductRoadmapDocument.model_validate(d)
        assert doc.tier_items[0].five_property_test_waiver is not None

    def test_both_fpt_and_waiver_raises(self) -> None:
        d = _doc(
            tier_items=[
                _item(
                    "L1.1",
                    tier="L1",
                    status="not_started",
                    five_property_test=_fpt(),
                    five_property_test_waiver=_waiver(),
                )
            ]
        )
        with pytest.raises(Exception, match="both"):
            ProductRoadmapDocument.model_validate(d)

    def test_waiver_missing_reason_raises(self) -> None:
        with pytest.raises(Exception):
            from scripts.roadmap.product_roadmap import FivePropertyWaiver

            FivePropertyWaiver.model_validate({"will_attest_when": "before status == in_progress"})

    def test_waiver_missing_will_attest_when_raises(self) -> None:
        with pytest.raises(Exception):
            from scripts.roadmap.product_roadmap import FivePropertyWaiver

            FivePropertyWaiver.model_validate({"reason": "test reason"})

    def test_waiver_empty_reason_raises(self) -> None:
        with pytest.raises(Exception, match="reason"):
            from scripts.roadmap.product_roadmap import FivePropertyWaiver

            FivePropertyWaiver.model_validate({"reason": "  ", "will_attest_when": "before status == in_progress"})

    def test_waiver_empty_will_attest_when_raises(self) -> None:
        with pytest.raises(Exception, match="will_attest_when"):
            from scripts.roadmap.product_roadmap import FivePropertyWaiver

            FivePropertyWaiver.model_validate({"reason": "test reason", "will_attest_when": ""})


# ---------------------------------------------------------------------------
# TestKnownPlatformGaps
# ---------------------------------------------------------------------------


class TestKnownPlatformGaps:
    def test_valid_pending_triage_passes(self) -> None:
        d = _doc(
            known_platform_gaps=[{"id": "GAP-my-gap", "description": "a gap", "intended_platform_tier_item": "pending_triage"}]
        )
        doc = ProductRoadmapDocument.model_validate(d)
        assert doc.known_platform_gaps[0].id == "GAP-my-gap"

    def test_missing_gap_prefix_raises(self) -> None:
        with pytest.raises(Exception, match="GAP-"):
            ProductRoadmapDocument.model_validate(
                _doc(
                    known_platform_gaps=[
                        {"id": "no-prefix-gap", "description": "a gap", "intended_platform_tier_item": "pending_triage"}
                    ]
                )
            )

    def test_nonexistent_intended_platform_item_raises(self) -> None:
        plat = _platform_doc(tier_items=[_platform_item("T0.1")])
        d = _doc(known_platform_gaps=[{"id": "GAP-test", "description": "a gap", "intended_platform_tier_item": "T999.0"}])
        with pytest.raises(Exception, match="not found"):
            ProductRoadmapDocument.model_validate(d, context={"platform_doc": plat})

    def test_pending_triage_always_passes_even_with_platform_doc(self) -> None:
        plat = _platform_doc(tier_items=[_platform_item("T0.1")])
        d = _doc(
            known_platform_gaps=[{"id": "GAP-test", "description": "a gap", "intended_platform_tier_item": "pending_triage"}]
        )
        doc = ProductRoadmapDocument.model_validate(d, context={"platform_doc": plat})
        assert doc.known_platform_gaps[0].intended_platform_tier_item == "pending_triage"

    def test_intended_platform_tier_item_accepts_cd_id(self) -> None:
        """PLAN-cd25-platform-gap-sequencing widens this validator to accept CD ids
        (e.g. GAP-cd25-contract-ritual resolves to CD.25, not a tier_item)."""
        plat = _platform_doc(
            tier_items=[_platform_item("T0.1")],
            cds=[{"id": "CD.25", "title": "Pre-codegen contract ratification"}],
        )
        d = _doc(known_platform_gaps=[{"id": "GAP-test", "description": "a gap", "intended_platform_tier_item": "CD.25"}])
        doc = ProductRoadmapDocument.model_validate(d, context={"platform_doc": plat})
        assert doc.known_platform_gaps[0].intended_platform_tier_item == "CD.25"

    def test_intended_platform_tier_item_unresolved_cd_raises(self) -> None:
        """A CD id that is not in the PLATFORM candidate_decisions[] still raises."""
        plat = _platform_doc(tier_items=[_platform_item("T0.1")])
        d = _doc(known_platform_gaps=[{"id": "GAP-test", "description": "a gap", "intended_platform_tier_item": "CD.999"}])
        with pytest.raises(Exception, match="not found"):
            ProductRoadmapDocument.model_validate(d, context={"platform_doc": plat})


# ---------------------------------------------------------------------------
# TestReverseIndex
# ---------------------------------------------------------------------------


class TestReverseIndex:
    @classmethod
    def _load_fixture_pair(cls):
        from scripts.roadmap.product_roadmap import ProductRoadmapState

        doc = load(
            FIXTURES / "minimal_product.yaml",
            platform_path=FIXTURES / "minimal_platform.yaml",
        )
        return ProductRoadmapState(doc)

    def test_platform_tier_item_consumers(self) -> None:
        state = self._load_fixture_pair()
        consumers = state.platform_tier_item_consumers()
        assert consumers.get("T-1.5") == ["L0.1"]
        assert consumers.get("T0.1") == ["D.fast.1", "L1.alpha.1"]
        assert consumers.get("T0.2") == ["L2.portfolio.1"]

    def test_platform_gap_consumers(self) -> None:
        state = self._load_fixture_pair()
        consumers = state.platform_gap_consumers()
        assert consumers.get("GAP-fixture-gap") == ["L1.alpha.1"]

    def test_platform_cd_consumers(self) -> None:
        state = self._load_fixture_pair()
        consumers = state.platform_cd_consumers()
        assert consumers.get("CD.1") == ["L1.alpha.1"]


# ---------------------------------------------------------------------------
# TestLiveYAML
# ---------------------------------------------------------------------------


_LIVE_PRODUCT = Path(__file__).parent.parent / "docs" / "ROADMAP-PRODUCT.yaml"
_LIVE_PLATFORM = Path(__file__).parent.parent / "docs" / "ROADMAP-PLATFORM.yaml"


@pytest.mark.skipif(not _LIVE_PRODUCT.exists(), reason="live ROADMAP-PRODUCT.yaml not present")
class TestLiveYAML:
    @classmethod
    def _state(cls):
        from scripts.roadmap.product_roadmap import ProductRoadmapState

        return ProductRoadmapState(load(_LIVE_PRODUCT, platform_path=_LIVE_PLATFORM))

    def test_live_yaml_loads(self) -> None:
        doc = load(_LIVE_PRODUCT, platform_path=_LIVE_PLATFORM)
        assert len(doc.tier_items) >= 70

    def test_t0_13_in_tier_item_consumers(self) -> None:
        state = self._state()
        consumers = state.platform_tier_item_consumers()
        assert "T0.13" in consumers
        assert "L0.1" in consumers["T0.13"]

    def test_all_six_gaps_resolved(self) -> None:
        """PLAN-cd25-platform-gap-sequencing resolved the six PLATFORM:GAP-* sentinels
        to concrete PLATFORM ids; the gap consumer map is now empty by design.
        The six gap ids remain in known_platform_gaps[] as a satisfied-gap audit trail
        with intended_platform_tier_item pointing at the resolved PLATFORM id."""
        state = self._state()
        gap_consumers = state.platform_gap_consumers()
        leftover = sorted(gap_consumers.keys())
        assert gap_consumers == {}, f"Unexpected GAP-* sentinels remain: {leftover}"

        # Audit trail still present in known_platform_gaps[] with resolved targets.
        doc = load(_LIVE_PRODUCT, platform_path=_LIVE_PLATFORM)
        gap_ids = {g.id for g in doc.known_platform_gaps}
        expected_gaps = {
            "GAP-cd25-contract-ritual",
            "GAP-t-1-12-product-contracts-schema-amendment",
            "GAP-tca-aggregation",
            "GAP-broker-secrets-manager",
            "GAP-reconciliation-lambda",
            "GAP-class-b-product-lambdas",
        }
        assert expected_gaps <= gap_ids, f"Missing satisfied-gap entries: {expected_gaps - gap_ids}"
        for gap in doc.known_platform_gaps:
            if gap.id in expected_gaps:
                assert gap.intended_platform_tier_item != "pending_triage", f"{gap.id} still pending_triage"

    def test_cd9_in_cd_consumers(self) -> None:
        state = self._state()
        cd_consumers = state.platform_cd_consumers()
        assert "CD.9" in cd_consumers
