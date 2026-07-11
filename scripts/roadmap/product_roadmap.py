# complexity-waiver: decision-43
"""Pydantic schema for docs/ROADMAP-PRODUCT.yaml, loader, and dependency-graph helpers."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

from scripts.roadmap.product_roadmap_schema import (  # noqa: F401
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
# Layer-shortcut constants (consumed by ProductRoadmapDocument._validate_graph
# and ProductRoadmapState; kept here next to their primary consumers)
# ---------------------------------------------------------------------------

# Matches PRODUCT layer shortcuts including aggregates (D -> D.fast + D.lake, E -> E.env)
_LAYER_SHORTCUT_RE = re.compile(r"^(?:L\d+|D(?:\.fast|\.lake)?|E(?:\.env)?|MVP)$")
_AGGREGATE_LAYER_SHORTCUTS: dict[str, list[str]] = {
    "D": ["D.fast", "D.lake"],
    "E": ["E.env"],
}
_CANONICAL_LAYER_ORDER: list[str] = ["L0", "L1", "L2", "L3", "L4", "D.fast", "D.lake", "E.env", "MVP"]


# ---------------------------------------------------------------------------
# Uniqueness helper used by ProductRoadmapDocument._validate_graph
# ---------------------------------------------------------------------------


def _check_unique_ids(items: list[Any], collection_name: str) -> None:
    seen: set[str] = set()
    for item in items:
        item_id = item.id
        if item_id in seen:
            raise ValueError(f"Duplicate id in {collection_name}: '{item_id}'")
        seen.add(item_id)


# ---------------------------------------------------------------------------
# ProductRoadmapDocument
# ---------------------------------------------------------------------------


class ProductRoadmapDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document: DocumentMeta
    north_star: NorthStar = Field(default_factory=NorthStar)
    current_state: CurrentState = Field(default_factory=CurrentState)
    four_layer_model: list[FourLayerEntry] = Field(default_factory=list)
    three_tier_data_architecture: ThreeTierData = Field(default_factory=ThreeTierData)
    environments: Environments = Field(default_factory=Environments)
    evaluation_metrics: EvaluationMetrics = Field(default_factory=EvaluationMetrics)
    minimum_viable_v1: MinimumViableV1 = Field(default_factory=MinimumViableV1)
    promotion_funnel: PromotionFunnel = Field(default_factory=PromotionFunnel)
    candidate_decisions: list[CandidateDecision] = Field(default_factory=list)
    candidate_decisions_research_pool: list[ResearchPoolDecision] = Field(default_factory=list)
    tier_items: list[TierItem] = Field(default_factory=list)
    cross_tier_gates: list[CrossTierGate] = Field(default_factory=list)
    retired_items: list[RetiredItem] = Field(default_factory=list)
    out_of_product_scope: list[OutOfProductScope] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    known_gaps: list[KnownGap] = Field(default_factory=list)
    known_platform_gaps: list[KnownPlatformGap] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_graph(self, info: ValidationInfo) -> "ProductRoadmapDocument":
        platform_doc = info.context.get("platform_doc") if info.context else None

        item_ids: set[str] = {item.id for item in self.tier_items}
        gap_ids: set[str] = {gap.id for gap in self.known_platform_gaps}

        # Build helpers: inherited PLATFORM + PRODUCT-local merged
        product_helpers: dict[str, int] = {gh.name: gh.arity for gh in self.document.gate_helpers}
        if platform_doc is not None:
            platform_helpers: dict[str, int] = {gh.name: gh.arity for gh in platform_doc.document.gate_helpers}
            helpers: dict[str, int] = {**platform_helpers, **product_helpers}
        else:
            helpers = product_helpers
            print(
                "WARNING: PLATFORM gate_helpers unavailable; gate-rule validation uses PRODUCT-local helpers only",
                file=sys.stderr,
            )

        # Build PLATFORM id sets
        if platform_doc is not None:
            platform_item_ids: set[str] = {item.id for item in platform_doc.tier_items}
            platform_restricted_ids: set[str] = {
                item.id for item in platform_doc.tier_items if item.status in {"reserved", "retired"}
            }
            platform_cd_ids: set[str] = {cd.id for cd in platform_doc.candidate_decisions}
        else:
            platform_item_ids = set()
            platform_restricted_ids = set()
            platform_cd_ids = set()

        # (a) ID uniqueness per collection
        _check_unique_ids(self.tier_items, "tier_items")
        _check_unique_ids(self.candidate_decisions, "candidate_decisions")
        _check_unique_ids(self.candidate_decisions_research_pool, "candidate_decisions_research_pool")
        _check_unique_ids(self.cross_tier_gates, "cross_tier_gates")
        _check_unique_ids(self.open_questions, "open_questions")
        _check_unique_ids(self.known_gaps, "known_gaps")
        _check_unique_ids(self.known_platform_gaps, "known_platform_gaps")

        # (b) Intra-roadmap depends_on resolution
        for item in self.tier_items:
            for dep in item.depends_on:
                if not (dep in item_ids or _LAYER_SHORTCUT_RE.match(dep)):
                    raise ValueError(
                        f"tier_item '{item.id}': depends_on '{dep}' does not resolve to a known id or layer shortcut"
                    )

        # (c) Cycle detection (DFS gray-set; layer shortcuts expand to per-tier sets)
        adj: dict[str, list[str]] = {item.id: [] for item in self.tier_items}
        for item in self.tier_items:
            for dep in item.depends_on:
                if dep in item_ids:
                    adj[item.id].append(dep)
                elif _LAYER_SHORTCUT_RE.match(dep):
                    # Expand aggregate (D -> D.fast + D.lake) or direct (D.fast -> D.fast)
                    sub_tiers = _AGGREGATE_LAYER_SHORTCUTS.get(dep, [dep])
                    for sub_tier in sub_tiers:
                        adj[item.id].extend(i.id for i in self.tier_items if i.tier == sub_tier)

        visited: set[str] = set()
        in_stack: set[str] = set()

        def _dfs(node: str) -> None:
            in_stack.add(node)
            visited.add(node)
            for neighbor in adj.get(node, []):
                if neighbor in in_stack:
                    raise ValueError(f"Dependency cycle detected: '{node}' -> '{neighbor}'")
                if neighbor not in visited:
                    _dfs(neighbor)
            in_stack.discard(node)

        for node in item_ids:
            if node not in visited:
                _dfs(node)

        # (d) candidate_decisions.gates resolution
        for cd in self.candidate_decisions:
            for ref in cd.gates:
                if not (ref in item_ids or _LAYER_SHORTCUT_RE.match(ref)):
                    raise ValueError(f"CandidateDecision '{cd.id}': gate ref '{ref}' does not resolve")

        # (e) Cross-roadmap resolution (three forms: PLATFORM tier_item, GAP, CD)
        if platform_doc is None:
            print(
                "WARNING: skipping cross-roadmap resolution -- PLATFORM YAML failed to load (platform_doc not provided)",
                file=sys.stderr,
            )
        else:
            for item in self.tier_items:
                for ref in item.cross_roadmap_depends_on:
                    if not ref.startswith("PLATFORM:"):
                        raise ValueError(
                            f"tier_item '{item.id}': cross_roadmap_depends_on '{ref}' must start with 'PLATFORM:'"
                        )
                    suffix = ref[len("PLATFORM:") :]
                    if suffix.startswith("GAP-"):
                        if suffix not in gap_ids:
                            raise ValueError(
                                f"tier_item '{item.id}': cross_roadmap_depends_on '{ref}' -- "
                                f"'{suffix}' not registered in known_platform_gaps"
                            )
                    elif suffix.startswith("CD."):
                        if suffix not in platform_cd_ids:
                            raise ValueError(
                                f"tier_item '{item.id}': cross_roadmap_depends_on '{ref}' -- "
                                f"'{suffix}' not found in PLATFORM candidate_decisions"
                            )
                    else:
                        # PLATFORM tier_item ref (T-1.6, T0.13, etc.)
                        if suffix not in platform_item_ids:
                            raise ValueError(
                                f"tier_item '{item.id}': cross_roadmap_depends_on '{ref}' does not resolve "
                                f"to a known PLATFORM tier_item id"
                            )
                        if suffix in platform_restricted_ids:
                            raise ValueError(
                                f"tier_item '{item.id}': cross_roadmap_depends_on '{ref}' -- "
                                f"PLATFORM tier_item '{suffix}' has restricted status (reserved/retired)"
                            )

        # (f) Gate-rule grammar validation
        for gate in self.cross_tier_gates:
            try:
                GateRuleParser.validate(gate.rule, helpers)
            except ValueError as exc:
                raise ValueError(f"CrossTierGate '{gate.id}': {exc}") from exc

        for cd in self.candidate_decisions:
            if cd.decision_required_before:
                try:
                    GateRuleParser.validate(cd.decision_required_before, helpers)
                except ValueError as exc:
                    raise ValueError(f"CandidateDecision '{cd.id}'.decision_required_before: {exc}") from exc

        # (g) Five-property test enforcement (XOR: test XOR waiver; exempt if status == complete)
        for item in self.tier_items:
            exempt = item.status == "complete"
            has_test = item.five_property_test is not None
            has_waiver = item.five_property_test_waiver is not None
            if not exempt:
                if has_test and has_waiver:
                    raise ValueError(
                        f"tier_item '{item.id}': cannot have both five_property_test AND five_property_test_waiver"
                    )
                if not has_test and not has_waiver:
                    raise ValueError(
                        f"tier_item '{item.id}': five_property_test required (or five_property_test_waiver). "
                        f"Status '{item.status}' is not 'complete' -- not exempt."
                    )

        # (h) KnownPlatformGap.intended_platform_tier_item resolution
        # Widened by PLAN-cd25-platform-gap-sequencing to accept BOTH tier_item ids and
        # candidate_decision ids -- a gap may be absorbed by a decision (e.g.
        # GAP-cd25-contract-ritual -> CD.25) as well as by a tier_item.
        for gap in self.known_platform_gaps:
            ipt = gap.intended_platform_tier_item
            if ipt != "pending_triage":
                if platform_doc is None:
                    raise ValueError(
                        f"KnownPlatformGap '{gap.id}': intended_platform_tier_item '{ipt}' "
                        "requires platform_doc but none is available"
                    )
                if ipt not in platform_item_ids and ipt not in platform_cd_ids:
                    raise ValueError(
                        f"KnownPlatformGap '{gap.id}': intended_platform_tier_item '{ipt}' "
                        "not found in PLATFORM tier_items or candidate_decisions"
                    )

        return self


# ---------------------------------------------------------------------------
# Helper and loader functions
# ---------------------------------------------------------------------------


def _item_dict(item: TierItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "tier": item.tier,
        "layer": item.layer,
        "name": item.name,
        "effort": item.effort,
        "strategic": item.strategic,
    }


def load(path: str | Path, platform_path: str | Path | None = None) -> ProductRoadmapDocument:
    """Parse the YAML roadmap at path and return a validated ProductRoadmapDocument."""
    with Path(path).open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    platform_doc = None
    if platform_path is not None:
        try:
            from scripts.roadmap.platform_roadmap import load as load_platform  # noqa: PLC0415

            platform_doc = load_platform(platform_path)
        except Exception as exc:  # noqa: BLE001
            print(
                f"WARNING: skipping cross-roadmap resolution -- PLATFORM YAML failed to load ({exc})",
                file=sys.stderr,
            )

    return ProductRoadmapDocument.model_validate(data, context={"platform_doc": platform_doc})


# ---------------------------------------------------------------------------
# ProductRoadmapState
# ---------------------------------------------------------------------------


class ProductRoadmapState:
    """Dependency-graph helpers for session_preflight and the planning skill."""

    def __init__(self, doc: ProductRoadmapDocument) -> None:
        self._doc = doc
        self._by_id: dict[str, TierItem] = {item.id: item for item in doc.tier_items}

    def layer_complete(self, layer: str) -> bool:
        if layer in _AGGREGATE_LAYER_SHORTCUTS:
            sub_tiers = _AGGREGATE_LAYER_SHORTCUTS[layer]
            items = [i for i in self._doc.tier_items if i.tier in sub_tiers and i.status != "reserved"]
        else:
            items = [i for i in self._doc.tier_items if i.tier == layer and i.status != "reserved"]
        return all(i.status == "complete" for i in items)

    def _dep_satisfied(self, dep: str) -> bool:
        if dep in self._by_id:
            return self._by_id[dep].status == "complete"
        # Layer shortcut (direct or aggregate)
        if _LAYER_SHORTCUT_RE.match(dep):
            return self.layer_complete(dep)
        return False

    def _blocked_on(self, item: TierItem) -> list[str]:
        return [dep for dep in item.depends_on if not self._dep_satisfied(dep)]

    def eligible_items(self) -> list[TierItem]:
        return [
            item
            for item in self._doc.tier_items
            if item.status == "not_started" and all(self._dep_satisfied(dep) for dep in item.depends_on)
        ]

    def compute_blocked(self) -> list[TierItem]:
        return [
            item
            for item in self._doc.tier_items
            if item.status == "not_started" and not all(self._dep_satisfied(dep) for dep in item.depends_on)
        ]

    def in_progress_items(self) -> list[TierItem]:
        return [item for item in self._doc.tier_items if item.status == "in_progress"]

    def strategic_pending_items(self) -> list[TierItem]:
        return [item for item in self.eligible_items() if item.strategic]

    def active_layer(self) -> str | None:
        for layer in _CANONICAL_LAYER_ORDER:
            if layer in _AGGREGATE_LAYER_SHORTCUTS:
                sub_tiers = _AGGREGATE_LAYER_SHORTCUTS[layer]
                layer_items = [i for i in self._doc.tier_items if i.tier in sub_tiers and i.status != "reserved"]
            else:
                layer_items = [i for i in self._doc.tier_items if i.tier == layer and i.status != "reserved"]
            if layer_items and not all(i.status == "complete" for i in layer_items):
                return layer
        return None

    def resolve_depends_on(self, item_id: str) -> list[TierItem]:
        item = self._by_id.get(item_id)
        if item is None:
            return []
        result: list[TierItem] = []
        for dep in item.depends_on:
            if dep in self._by_id:
                result.append(self._by_id[dep])
            elif _LAYER_SHORTCUT_RE.match(dep):
                sub_tiers = _AGGREGATE_LAYER_SHORTCUTS.get(dep, [dep])
                for sub_tier in sub_tiers:
                    result.extend(i for i in self._doc.tier_items if i.tier == sub_tier and i.status != "reserved")
        return result

    def platform_tier_item_consumers(self) -> dict[str, list[str]]:
        """Map PLATFORM tier_item id -> sorted list of PRODUCT tier_item ids that depend on it."""
        result: dict[str, list[str]] = {}
        for item in self._doc.tier_items:
            for ref in item.cross_roadmap_depends_on:
                if not ref.startswith("PLATFORM:"):
                    continue
                suffix = ref[len("PLATFORM:") :]
                if suffix.startswith("GAP-") or suffix.startswith("CD."):
                    continue
                result.setdefault(suffix, [])
                if item.id not in result[suffix]:
                    result[suffix].append(item.id)
        return {k: sorted(v) for k, v in result.items()}

    def platform_gap_consumers(self) -> dict[str, list[str]]:
        """Map PLATFORM GAP slug -> sorted list of PRODUCT tier_item ids that depend on it."""
        result: dict[str, list[str]] = {}
        for item in self._doc.tier_items:
            for ref in item.cross_roadmap_depends_on:
                if not ref.startswith("PLATFORM:GAP-"):
                    continue
                gap_id = ref[len("PLATFORM:") :]  # e.g. "GAP-cd25-contract-ritual"
                result.setdefault(gap_id, [])
                if item.id not in result[gap_id]:
                    result[gap_id].append(item.id)
        return {k: sorted(v) for k, v in result.items()}

    def platform_cd_consumers(self) -> dict[str, list[str]]:
        """Map PLATFORM CD id -> sorted list of PRODUCT tier_item ids that depend on it."""
        result: dict[str, list[str]] = {}
        for item in self._doc.tier_items:
            for ref in item.cross_roadmap_depends_on:
                if not ref.startswith("PLATFORM:CD."):
                    continue
                cd_id = ref[len("PLATFORM:") :]  # e.g. "CD.9"
                result.setdefault(cd_id, [])
                if item.id not in result[cd_id]:
                    result[cd_id].append(item.id)
        return {k: sorted(v) for k, v in result.items()}

    def to_preflight_dict(self) -> dict[str, Any]:
        return {
            "next_eligible": [_item_dict(i) for i in self.eligible_items() if not i.strategic],
            "in_progress": [_item_dict(i) for i in self.in_progress_items()],
            "blocked": [{**_item_dict(i), "blocked_on": self._blocked_on(i)} for i in self.compute_blocked()],
            "strategic_pending": [_item_dict(i) for i in self.strategic_pending_items()],
            "active_layer": self.active_layer(),
            "platform_tier_item_consumers": self.platform_tier_item_consumers(),
            "platform_gap_consumers": self.platform_gap_consumers(),
            "platform_cd_consumers": self.platform_cd_consumers(),
        }


# ---------------------------------------------------------------------------
# compute_state_dict
# ---------------------------------------------------------------------------


def compute_state_dict(
    yaml_path: Path,
    platform_yaml_path: Path | None = None,
    *,
    latest_decision_ts: str | None = None,
) -> dict[str, Any]:
    """Compute product roadmap state; returns JSON-serialisable dict for session_preflight.

    On parse error or missing file, returns a dict with an 'error' key and empty collections.
    """
    try:
        doc = load(yaml_path, platform_path=platform_yaml_path)
    except Exception as exc:  # noqa: BLE001
        return {
            "error": str(exc),
            "next_eligible": [],
            "in_progress": [],
            "blocked": [],
            "strategic_pending": [],
            "active_layer": None,
            "platform_tier_item_consumers": {},
            "platform_gap_consumers": {},
            "platform_cd_consumers": {},
        }

    state = ProductRoadmapState(doc)
    result = state.to_preflight_dict()

    if latest_decision_ts is not None:
        try:
            yaml_mtime = datetime.fromtimestamp(Path(yaml_path).stat().st_mtime, tz=timezone.utc)
            decision_dt = datetime.fromisoformat(latest_decision_ts.replace(" ", "T").rstrip("Z"))
            if decision_dt.tzinfo is None:
                decision_dt = decision_dt.replace(tzinfo=timezone.utc)
            if yaml_mtime > decision_dt:
                result["stale_cache_note"] = (
                    f"roadmap edits awaiting ratification: YAML mtime {yaml_mtime.isoformat()} "
                    f"newer than latest decision {decision_dt.isoformat()}"
                )
        except Exception:  # noqa: BLE001
            pass

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Product roadmap validator")
    parser.add_argument("--check", metavar="PATH", help="Load and validate PRODUCT YAML; print PASS/FAIL")
    parser.add_argument("--platform", metavar="PATH", help="PLATFORM YAML for cross-roadmap resolution")
    parser.add_argument("--check-preflight-report", metavar="PATH", help="Assert preflight report has product_roadmap block")
    parser.add_argument("--list-waiver-candidates", metavar="PATH", help="List tier_items needing five_property_test waivers")
    args = parser.parse_args()

    if args.list_waiver_candidates:
        with open(args.list_waiver_candidates, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        candidates = [
            item["id"]
            for item in raw.get("tier_items", [])
            if "five_property_test" not in item
            and "five_property_test_waiver" not in item
            and item.get("status") != "complete"
        ]
        print(f"Waiver candidates ({len(candidates)}):")
        for c in candidates:
            print(f"  {c}")
        sys.exit(0)

    if args.check_preflight_report:
        with open(args.check_preflight_report, encoding="utf-8") as fh:
            report = json.load(fh)
        block = report.get("product_roadmap")
        if block is None:
            print("FAIL: 'product_roadmap' key missing from preflight report")
            sys.exit(1)
        expected_keys = {
            "next_eligible",
            "in_progress",
            "blocked",
            "strategic_pending",
            "active_layer",
            "platform_tier_item_consumers",
            "platform_gap_consumers",
            "platform_cd_consumers",
        }
        missing = expected_keys - set(block.keys())
        if missing:
            print(f"FAIL: product_roadmap block missing keys: {sorted(missing)}")
            sys.exit(1)
        if not isinstance(block["platform_tier_item_consumers"], dict):
            print("FAIL: platform_tier_item_consumers should be a dict")
            sys.exit(1)
        if not isinstance(block["platform_gap_consumers"], dict):
            print("FAIL: platform_gap_consumers should be a dict")
            sys.exit(1)
        if not isinstance(block["platform_cd_consumers"], dict):
            print("FAIL: platform_cd_consumers should be a dict")
            sys.exit(1)
        print("PASS: preflight report has correct product_roadmap block shape")
        sys.exit(0)

    if args.check:
        product_path = Path(args.check)
        platform_path = Path(args.platform) if args.platform else None
        try:
            doc = load(product_path, platform_path=platform_path)
            state = ProductRoadmapState(doc)
            n_tier = len(state.platform_tier_item_consumers())
            n_gap = len(state.platform_gap_consumers())
            n_cd = len(state.platform_cd_consumers())
            print("PASS: product roadmap schema validation passed.")
            print(f"platform_consumers: {n_tier + n_gap + n_cd} entries ({n_tier} tier_item, {n_gap} gap, {n_cd} cd)")
            sys.exit(0)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL: {exc}")
            sys.exit(1)

    parser.print_help()
    sys.exit(1)
