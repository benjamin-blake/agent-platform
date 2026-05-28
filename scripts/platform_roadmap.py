# complexity-waiver: decision-43
"""Pydantic schema for docs/ROADMAP-PLATFORM.yaml, loader, and dependency-graph helpers."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SUPPORTED_VERSIONS: frozenset[int] = frozenset({1})
_OPS_DECISIONS_RE = re.compile(r"^ops_decisions:dec-\d+$")
_TIER_SHORTCUT_RE = re.compile(r"^T-?\d+$")
_CANONICAL_TIER_ORDER: list[str] = ["T-1", "T0", "T1", "T2", "T3", "T4", "T5"]

# Canonical helper table: name -> expected arity. Populated from document.gate_helpers
# at validation time; this module-level dict is the fallback for test fixtures without
# a gate_helpers section.
_GATE_HELPERS: dict[str, int] = {
    "tier_complete": 1,
    "all_in_tier_with_status": 2,
    "grace_period_elapsed": 2,
    "item_field_eq": 3,
}


class GateRuleParser:
    """Validates gate-rule expressions against the gate_helpers table.

    Tokenises function calls only (name + arity). Never evaluates. Field-path
    resolution is a runtime concern handled by T-1.4.
    """

    _CALL_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\(")

    @classmethod
    def validate(cls, rule: str, helpers: dict[str, int]) -> None:
        for m in cls._CALL_RE.finditer(rule):
            name = m.group(1)
            if name not in helpers:
                raise ValueError(f"Unknown gate-rule helper '{name}'. Valid: {sorted(helpers)}")
            close = cls._find_close(rule, m.end())
            arity = cls._count_args(rule[m.end() : close])
            if arity != helpers[name]:
                raise ValueError(f"Helper '{name}': expected {helpers[name]} arg(s), got {arity}")

    @staticmethod
    def _find_close(s: str, start: int) -> int:
        depth, i = 1, start
        while i < len(s) and depth:
            if s[i] == "(":
                depth += 1
            elif s[i] == ")":
                depth -= 1
            i += 1
        return i - 1

    @staticmethod
    def _count_args(s: str) -> int:
        s = s.strip()
        if not s:
            return 0
        depth, in_str, str_char, count = 0, False, "", 1
        for ch in s:
            if in_str:
                if ch == str_char:
                    in_str = False
            elif ch in ('"', "'"):
                in_str, str_char = True, ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and not depth:
                count += 1
        return count


class GateHelper(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    arity: int
    params: list[dict[str, Any]] = Field(default_factory=list)
    returns: str = "bool"
    semantics: str = ""


class DocumentMeta(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    version: int
    status: str
    filed_via: str
    description: str = ""
    agent_instructions: str = ""
    gate_helpers: list[GateHelper] = Field(default_factory=list)

    @field_validator("version")
    @classmethod
    def _check_version(cls, v: int) -> int:
        if v not in _SUPPORTED_VERSIONS:
            raise ValueError(f"Unsupported document version {v}. Supported: {sorted(_SUPPORTED_VERSIONS)}")
        return v

    @field_validator("filed_via")
    @classmethod
    def _check_filed_via(cls, v: str) -> str:
        if v == "pending_log_decision_lambda" or _OPS_DECISIONS_RE.match(v):
            return v
        raise ValueError(f"Invalid filed_via '{v}'. Must be 'pending_log_decision_lambda' or 'ops_decisions:dec-<NNN>'")


class TierItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    tier: str
    name: str
    intent: str = ""
    depends_on: list[str] = Field(default_factory=list)
    files_in_scope: list[str] = Field(default_factory=list)
    exit_criteria: list[str] = Field(default_factory=list)
    related_candidate_decisions: list[str] = Field(default_factory=list)
    related_intents: list[str] | None = None
    related_decisions: list[int] | None = None
    effort: Literal["XS", "S", "M", "L", "XL"] = "S"
    strategic: bool = False
    status: Literal["not_started", "in_progress", "complete", "reserved"] = "not_started"
    completed_at: str | None = None
    note: str | None = None
    progress_note: str | None = None
    bootstrap_completion_exempt: bool = False
    decision_required_before: list[str] | None = None
    decomposition_hints: dict[str, Any] | None = None
    consumer_fixups: list[str] | None = None
    minimum_verbs: list[str] | None = None
    rename_history: dict[str, Any] | None = None
    user_action_required: bool | None = None


class CandidateDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    detail: str = ""
    gates: list[str] = Field(default_factory=list)
    state: str = "pending"
    decision_required_before: list[str] | str | None = None
    bootstrap_allowance: bool = False
    filed_via: str | None = None
    narrowly_supersedes: dict[str, Any] | None = None
    supersedes_intents: list[str] | None = None
    supersedes_decisions: list[Any] | None = None
    retires_intents: list[str] | None = None
    demotes_intents: list[str] | None = None
    discipline_points: list[Any] | None = None
    enforcement_mechanism: str | None = None


class CrossTierGate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    name: str
    rule: str
    rationale: str = ""


class OpenQuestion(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    question: str
    resolution_tier: str = ""
    notes: str = ""


class KnownGap(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    gap: str
    notes: str = ""


class NorthStarPrinciple(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    principle: str
    detail: str = ""


class NorthStar(BaseModel):
    model_config = ConfigDict(extra="ignore")
    principles: list[NorthStarPrinciple] = Field(default_factory=list)


class FoundationItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    name: str
    notes: str = ""


class RoadmapDocument(BaseModel):
    model_config = ConfigDict(extra="ignore")

    document: DocumentMeta
    north_star: NorthStar = Field(default_factory=NorthStar)
    cost_projection: dict[str, Any] = Field(default_factory=dict)
    rebuild_vs_refactor: dict[str, Any] = Field(default_factory=dict)
    foundation_already_shipped: list[FoundationItem] = Field(default_factory=list)
    candidate_decisions: list[CandidateDecision] = Field(default_factory=list)
    tier_items: list[TierItem] = Field(default_factory=list)
    cross_tier_gates: list[CrossTierGate] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    known_gaps: list[KnownGap] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_graph(self) -> RoadmapDocument:
        item_ids: set[str] = {item.id for item in self.tier_items}
        helpers: dict[str, int] = (
            {gh.name: gh.arity for gh in self.document.gate_helpers} if self.document.gate_helpers else _GATE_HELPERS.copy()
        )

        # (a) id uniqueness
        seen: set[str] = set()
        for item in self.tier_items:
            if item.id in seen:
                raise ValueError(f"Duplicate tier_item id: '{item.id}'")
            seen.add(item.id)

        # (b) depends_on resolution
        for item in self.tier_items:
            for dep in item.depends_on:
                if not (_TIER_SHORTCUT_RE.match(dep) or dep in item_ids):
                    raise ValueError(
                        f"tier_item '{item.id}': depends_on '{dep}' does not resolve to a known id or tier shortcut"
                    )

        # (c) cycle detection (DFS, gray-set algorithm)
        adj: dict[str, list[str]] = {item.id: [] for item in self.tier_items}
        for item in self.tier_items:
            for dep in item.depends_on:
                if dep in item_ids:
                    adj[item.id].append(dep)
                elif _TIER_SHORTCUT_RE.match(dep):
                    adj[item.id].extend(i.id for i in self.tier_items if i.tier == dep)

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
                if not (_TIER_SHORTCUT_RE.match(ref) or ref in item_ids):
                    raise ValueError(f"CandidateDecision '{cd.id}': gate ref '{ref}' does not resolve")

        # (e) gate-rule grammar validation
        for gate in self.cross_tier_gates:
            try:
                GateRuleParser.validate(gate.rule, helpers)
            except ValueError as exc:
                raise ValueError(f"CrossTierGate '{gate.id}': {exc}") from exc

        for cd in self.candidate_decisions:
            drb = cd.decision_required_before
            if drb:
                # Widened to list[str] | str | None (T-1.12). Each grammar-shaped string is
                # validated; non-grammar prose entries (e.g. "T0.13 may start") have no
                # function calls and are no-ops under GateRuleParser. List form is iterated.
                entries = drb if isinstance(drb, list) else [drb]
                for entry in entries:
                    if not isinstance(entry, str):
                        continue
                    try:
                        GateRuleParser.validate(entry, helpers)
                    except ValueError as exc:
                        raise ValueError(f"CandidateDecision '{cd.id}'.decision_required_before: {exc}") from exc

        return self


def _item_dict(item: TierItem) -> dict[str, Any]:
    return {"id": item.id, "tier": item.tier, "name": item.name, "effort": item.effort, "strategic": item.strategic}


def load(path: str | Path) -> RoadmapDocument:
    """Parse the YAML roadmap at path and return a validated RoadmapDocument."""
    with Path(path).open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return RoadmapDocument.model_validate(data)


class PlatformRoadmapState:
    """Dependency-graph helpers for T-1.4 (preflight) and T-1.2 (planning skill).

    Encapsulates tier-name shortcut resolution per agent_instructions semantics so
    T-1.4 gets a thin shim instead of re-implementing the graph traversal.
    """

    def __init__(self, doc: RoadmapDocument) -> None:
        self._doc = doc
        self._by_id: dict[str, TierItem] = {item.id: item for item in doc.tier_items}

    def tier_complete(self, tier_name: str) -> bool:
        return all(
            item.status == "complete" for item in self._doc.tier_items if item.tier == tier_name and item.status != "reserved"
        )

    def resolve_depends_on(self, item_id: str) -> list[TierItem]:
        item = self._by_id.get(item_id)
        if item is None:
            return []
        result: list[TierItem] = []
        for dep in item.depends_on:
            if _TIER_SHORTCUT_RE.match(dep):
                result.extend(i for i in self._doc.tier_items if i.tier == dep and i.status != "reserved")
            elif dep in self._by_id:
                result.append(self._by_id[dep])
        return result

    def _dep_satisfied(self, dep: str) -> bool:
        if _TIER_SHORTCUT_RE.match(dep):
            return self.tier_complete(dep)
        item = self._by_id.get(dep)
        return item is not None and item.status == "complete"

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

    def active_tier(self) -> str | None:
        for tier_name in _CANONICAL_TIER_ORDER:
            tier_items = [i for i in self._doc.tier_items if i.tier == tier_name and i.status != "reserved"]
            if tier_items and not all(i.status == "complete" for i in tier_items):
                return tier_name
        return None

    def _blocked_on(self, item: TierItem) -> list[str]:
        return [dep for dep in item.depends_on if not self._dep_satisfied(dep)]

    def to_preflight_dict(self) -> dict[str, Any]:
        return {
            "next_eligible": [_item_dict(i) for i in self.eligible_items() if not i.strategic],
            "in_progress": [_item_dict(i) for i in self.in_progress_items()],
            "blocked": [{**_item_dict(i), "blocked_on": self._blocked_on(i)} for i in self.compute_blocked()],
            "strategic_pending": [_item_dict(i) for i in self.strategic_pending_items()],
            "active_tier": self.active_tier(),
        }


def compute_state_dict(yaml_path: Path, *, latest_decision_ts: str | None = None) -> dict[str, Any]:
    """Compute roadmap state and return a JSON-serialisable dict for session_preflight.

    On parse error or missing file, returns a dict with an 'error' key and empty lists.
    When latest_decision_ts is provided and YAML mtime is strictly newer, a stale_cache_note
    is included in the result.
    """
    try:
        doc = load(yaml_path)
    except Exception as exc:  # noqa: BLE001
        return {
            "error": str(exc),
            "next_eligible": [],
            "in_progress": [],
            "blocked": [],
            "strategic_pending": [],
            "active_tier": None,
        }

    state = PlatformRoadmapState(doc)
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Platform roadmap validator")
    parser.add_argument("path", nargs="?", default="docs/ROADMAP-PLATFORM.yaml", help="Path to ROADMAP-PLATFORM.yaml")
    args = parser.parse_args()
    try:
        load(Path(args.path))
        print(f"PASS: {args.path} validates against RoadmapDocument schema.")
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc}")
        sys.exit(1)
