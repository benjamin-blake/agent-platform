"""Tests for scripts/roadmap/product_roadmap_schema.py -- 100% line coverage target."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from scripts.roadmap.product_roadmap_schema import (
    CandidateDecision,
    ContractGate,
    CrossTierGate,
    CurrentState,
    DocumentMeta,
    Environments,
    EvaluationMetrics,
    FivePropertyAttestation,
    FivePropertyTest,
    FivePropertyWaiver,
    FourLayerEntry,
    GateHelper,
    GateRuleParser,
    KnownGap,
    KnownPlatformGap,
    MinimumViableV1,
    NorthStar,
    OpenQuestion,
    OutOfProductScope,
    PromotionFunnel,
    ResearchPoolDecision,
    RetiredItem,
    ThreeTierData,
    TierItem,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_BASE_META = {
    "id": "TEST-DOC",
    "version": 1,
    "status": "draft",
    "filed_via": "pending_log_decision_lambda",
}

_ATTESTATION = {"attestation": "attested", "cites": "ref-1"}

_FIVE_PROPS = {
    "parameterised": _ATTESTATION,
    "versioned": _ATTESTATION,
    "composable": _ATTESTATION,
    "observable": _ATTESTATION,
    "evaluable": _ATTESTATION,
}


# ---------------------------------------------------------------------------
# GateRuleParser
# ---------------------------------------------------------------------------


class TestGateRuleParser:
    def test_no_function_calls(self):
        """Rule with no call syntax produces no error."""
        GateRuleParser.validate("x > 0 and y < 1", {})

    def test_valid_single_call(self):
        """Valid call with matching arity succeeds."""
        GateRuleParser.validate("f(x, y)", {"f": 2})

    def test_zero_arity_call(self):
        """Zero-arity call exercises the empty-args branch in _count_args."""
        GateRuleParser.validate("f()", {"f": 0})

    def test_unknown_helper_raises(self):
        """Unknown helper name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown gate-rule helper"):
            GateRuleParser.validate("foo(x)", {"bar": 1})

    def test_wrong_arity_raises(self):
        """Arity mismatch raises ValueError."""
        with pytest.raises(ValueError, match="expected 1"):
            GateRuleParser.validate("f(x, y)", {"f": 1})

    def test_double_quote_string_comma_ignored(self):
        """Comma inside double-quoted string does not count as arg separator."""
        GateRuleParser.validate('f("a,b")', {"f": 1})

    def test_single_quote_string_comma_ignored(self):
        """Comma inside single-quoted string does not count as arg separator."""
        GateRuleParser.validate("f('a,b')", {"f": 1})

    def test_nested_parens_depth_tracking(self):
        """Comma inside nested parens is not counted; closing paren decrements depth in _count_args."""
        GateRuleParser.validate("f(g(x), y)", {"f": 2, "g": 1})


# ---------------------------------------------------------------------------
# GateHelper
# ---------------------------------------------------------------------------


class TestGateHelper:
    def test_construction(self):
        gh = GateHelper(name="deflated_sharpe", arity=3)
        assert gh.name == "deflated_sharpe"
        assert gh.arity == 3
        assert gh.returns == "bool"


# ---------------------------------------------------------------------------
# DocumentMeta
# ---------------------------------------------------------------------------


class TestDocumentMeta:
    def test_valid_pending_filed_via(self):
        doc = DocumentMeta.model_validate(_BASE_META)
        assert doc.version == 1

    def test_valid_ops_decisions_filed_via(self):
        meta = {**_BASE_META, "filed_via": "ops_decisions:dec-42"}
        doc = DocumentMeta.model_validate(meta)
        assert doc.filed_via == "ops_decisions:dec-42"

    def test_invalid_version_raises(self):
        meta = {**_BASE_META, "version": 99}
        with pytest.raises(ValidationError, match="Unsupported document version"):
            DocumentMeta.model_validate(meta)

    def test_invalid_filed_via_raises(self):
        meta = {**_BASE_META, "filed_via": "not_valid"}
        with pytest.raises(ValidationError, match="Invalid filed_via"):
            DocumentMeta.model_validate(meta)


# ---------------------------------------------------------------------------
# FourLayerEntry
# ---------------------------------------------------------------------------


class TestFourLayerEntry:
    def test_construction(self):
        entry = FourLayerEntry(layer="L0", name="Ingestion")
        assert entry.layer == "L0"


# ---------------------------------------------------------------------------
# Simple extra="ignore" models
# ---------------------------------------------------------------------------


class TestSimpleIgnoreModels:
    def test_current_state(self):
        CurrentState()
        CurrentState.model_validate({"extra_key": "ignored"})

    def test_three_tier_data(self):
        ThreeTierData()

    def test_environments(self):
        Environments()

    def test_evaluation_metrics(self):
        EvaluationMetrics()

    def test_minimum_viable_v1(self):
        MinimumViableV1()

    def test_promotion_funnel(self):
        PromotionFunnel()

    def test_north_star(self):
        ns = NorthStar(principles=["p1"])
        assert ns.principles == ["p1"]


# ---------------------------------------------------------------------------
# ContractGate (uses 'class' alias)
# ---------------------------------------------------------------------------


class TestContractGate:
    def test_construction_via_alias(self):
        gate = ContractGate.model_validate({"path": "src/x.py", "class": "A", "contract_version": 2})
        assert gate.contract_class == "A"

    def test_construction_via_field_name(self):
        gate = ContractGate(path="src/x.py", contract_class="B", contract_version=1)
        assert gate.contract_class == "B"


# ---------------------------------------------------------------------------
# FiveProperty* models
# ---------------------------------------------------------------------------


class TestFivePropertyModels:
    def test_attestation(self):
        a = FivePropertyAttestation(attestation="yes", cites="ref-1")
        assert a.cites == "ref-1"

    def test_five_property_test(self):
        fpt = FivePropertyTest.model_validate(_FIVE_PROPS)
        assert fpt.parameterised.attestation == "attested"

    def test_waiver_valid(self):
        w = FivePropertyWaiver(reason="not ready", will_attest_when="T-1.5 complete")
        assert w.reason == "not ready"

    def test_waiver_empty_reason_raises(self):
        with pytest.raises(ValidationError, match="reason must be non-empty"):
            FivePropertyWaiver(reason="", will_attest_when="some date")

    def test_waiver_empty_will_attest_when_raises(self):
        with pytest.raises(ValidationError, match="will_attest_when must be non-empty"):
            FivePropertyWaiver(reason="valid reason", will_attest_when="")


# ---------------------------------------------------------------------------
# TierItem
# ---------------------------------------------------------------------------


class TestTierItem:
    def test_minimal_construction(self):
        item = TierItem(id="T-1.1", tier="L0", layer="L0", name="Ingestion")
        assert item.status == "not_started"
        assert item.effort == "S"

    def test_with_waiver(self):
        item = TierItem(
            id="T-1.2",
            tier="L0",
            layer="L0",
            name="Item with waiver",
            five_property_test_waiver=FivePropertyWaiver(reason="r", will_attest_when="w"),
        )
        assert item.five_property_test_waiver is not None


# ---------------------------------------------------------------------------
# CandidateDecision
# ---------------------------------------------------------------------------


class TestCandidateDecision:
    def test_construction(self):
        cd = CandidateDecision(id="CD.1", title="Test decision")
        assert cd.state == "pending"


# ---------------------------------------------------------------------------
# ResearchPoolDecision
# ---------------------------------------------------------------------------


class TestResearchPoolDecision:
    def test_construction(self):
        rpd = ResearchPoolDecision(id="CD.2", title="Research item")
        assert rpd.id == "CD.2"


# ---------------------------------------------------------------------------
# CrossTierGate
# ---------------------------------------------------------------------------


class TestCrossTierGate:
    def test_construction(self):
        gate = CrossTierGate(id="CTG-1", name="Gate A", rule="f(x)")
        assert gate.name == "Gate A"


# ---------------------------------------------------------------------------
# RetiredItem, OutOfProductScope, OpenQuestion, KnownGap
# ---------------------------------------------------------------------------


class TestMiscModels:
    def test_retired_item(self):
        RetiredItem(source_section="sec1", reason="obsolete")

    def test_out_of_product_scope(self):
        OutOfProductScope(text="some thing", disposition="out")

    def test_open_question(self):
        oq = OpenQuestion(id="OQ-1", question="what?")
        assert oq.id == "OQ-1"

    def test_known_gap(self):
        kg = KnownGap(id="KG-1", gap="missing feature")
        assert kg.id == "KG-1"


# ---------------------------------------------------------------------------
# KnownPlatformGap
# ---------------------------------------------------------------------------


class TestKnownPlatformGap:
    def test_valid_gap_id(self):
        gap = KnownPlatformGap(id="GAP-cd25-contract", intended_platform_tier_item="pending_triage")
        assert gap.id == "GAP-cd25-contract"

    def test_invalid_gap_id_raises(self):
        with pytest.raises(ValidationError, match=r"id must match"):
            KnownPlatformGap(id="INVALID-FORMAT", intended_platform_tier_item="pending_triage")


# ---------------------------------------------------------------------------
# TestPlatformGapSentinelRetired -- PLAN-cd25-platform-gap-sequencing
# Asserts the live ROADMAP-PRODUCT.yaml has no PLATFORM:GAP-* sentinels in
# cross_roadmap_depends_on, and that every PLATFORM:<id> reference resolves
# to a real PLATFORM tier_item or candidate_decision id.
# ---------------------------------------------------------------------------


class TestPlatformGapSentinelRetired:
    @staticmethod
    def _load_product():
        from pathlib import Path  # noqa: PLC0415

        import yaml as _yaml  # noqa: PLC0415

        path = Path(__file__).parent.parent / "docs" / "ROADMAP-PRODUCT.yaml"
        with path.open(encoding="utf-8") as fh:
            return _yaml.safe_load(fh)

    @staticmethod
    def _load_platform_ids():
        from pathlib import Path  # noqa: PLC0415

        import yaml as _yaml  # noqa: PLC0415

        path = Path(__file__).parent.parent / "docs" / "ROADMAP-PLATFORM.yaml"
        with path.open(encoding="utf-8") as fh:
            data = _yaml.safe_load(fh)
        tier_ids = {i["id"] for i in (data.get("tier_items") or [])}
        cd_ids = {c["id"] for c in (data.get("candidate_decisions") or [])}
        return tier_ids | cd_ids

    def test_no_platform_gap_in_cross_edges(self):
        """Asserts no tier_item's cross_roadmap_depends_on contains a PLATFORM:GAP-* value."""
        data = self._load_product()
        bad = [
            (t["id"], v)
            for t in (data.get("tier_items") or [])
            for v in (t.get("cross_roadmap_depends_on") or [])
            if isinstance(v, str) and v.startswith("PLATFORM:GAP-")
        ]
        assert not bad, f"PLATFORM:GAP-* sentinels remain in cross_roadmap_depends_on: {bad}"

    def test_platform_cross_edges_resolve(self):
        """Asserts every PLATFORM:<id> reference in PRODUCT's cross_roadmap_depends_on
        resolves to a real PLATFORM tier_item or candidate_decision id."""
        import re  # noqa: PLC0415

        data = self._load_product()
        platform_ids = self._load_platform_ids()
        orphans = [
            (t["id"], v)
            for t in (data.get("tier_items") or [])
            for v in (t.get("cross_roadmap_depends_on") or [])
            if isinstance(v, str) and v.startswith("PLATFORM:") and re.sub(r"^PLATFORM:", "", v) not in platform_ids
        ]
        assert not orphans, f"Unresolved PLATFORM refs: {orphans}"

    def test_known_platform_gaps_fully_resolved(self):
        """Asserts known_platform_gaps[] block has no pending_triage values and all
        intended_platform_tier_item values resolve to real PLATFORM ids."""
        data = self._load_product()
        platform_ids = self._load_platform_ids()
        pending = [
            g["id"]
            for g in (data.get("known_platform_gaps") or [])
            if g.get("intended_platform_tier_item") == "pending_triage"
        ]
        assert not pending, f"pending_triage entries remain: {pending}"
        bad = [
            (g["id"], g.get("intended_platform_tier_item"))
            for g in (data.get("known_platform_gaps") or [])
            if g.get("intended_platform_tier_item") not in platform_ids
        ]
        assert not bad, f"known_platform_gaps with unresolved targets: {bad}"
