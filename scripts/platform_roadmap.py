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
_CD_REF_RE = re.compile(r"\b(CD\.\d+)\b")
_CANONICAL_TIER_ORDER: list[str] = ["T-1", "T0", "T1", "T2", "T3", "T4", "T5"]
_INACTIVE_FOR_TIER: frozenset[str] = frozenset({"reserved", "deferred_post_mvp"})

# Canonical helper table: name -> expected arity. Populated from document.gate_helpers
# at validation time; this module-level dict is the fallback for test fixtures without
# a gate_helpers section.
_GATE_HELPERS: dict[str, int] = {
    "tier_complete": 1,
    "all_in_tier_with_status": 2,
    "grace_period_elapsed": 2,
    "item_field_eq": 3,
}

# ---------------------------------------------------------------------------
# Gate-rule evaluator (GateRuleEvaluator) -- T-1.20
#
# No eval()/exec(). Tokenizer + recursive-descent over the gate mini-grammar.
# Three-valued (Kleene) logic with proper short-circuit:
#   false AND deferred -> false  (not deferred-poisoning)
#   true  OR  deferred -> true   (not deferred-poisoning)
# Static fields: only 'status' is resolvable from the YAML. Any other field
# path (latest_run.verdict, uptime_days, ...) and item_field_eq -> deferred.
# Field-path resolution: longest-known-tier-item-id prefix (dot-delimited).
# ---------------------------------------------------------------------------

_EVAL_TOKEN_RE = re.compile(
    r'(?P<STRING>"[^"]*"|\'[^\']*\')'
    r"|(?P<NUMBER>\d+)"
    r"|(?P<OP>==)"
    r"|(?P<LPAREN>\()"
    r"|(?P<RPAREN>\))"
    r"|(?P<COMMA>,)"
    r"|(?P<NAME>[A-Za-z_][A-Za-z0-9_.\\-]*)"
    r"|(?P<WS>\s+)"
)


class _Token:
    __slots__ = ("kind", "value")

    def __init__(self, kind: str, value: str) -> None:
        self.kind = kind
        self.value = value


def _tokenize(rule: str) -> list[_Token]:
    tokens: list[_Token] = []
    for m in _EVAL_TOKEN_RE.finditer(rule):
        kind = m.lastgroup
        if kind == "WS":
            continue
        value = m.group()
        if kind == "STRING":
            value = value[1:-1]
        elif kind == "NAME" and value in ("and", "or", "not"):
            kind = "KEYWORD"
        if kind is None:
            raise ValueError(f"_tokenize: regex matched but lastgroup is None for {m.group()!r}")
        tokens.append(_Token(kind, value))
    tokens.append(_Token("EOF", ""))
    return tokens


_Verdict = str  # "pass" | "fail" | "deferred"


class GateRuleEvaluator:
    """Recursive-descent evaluator for cross-tier gate rule expressions.

    Implements Kleene three-valued logic with proper short-circuit so a false
    conjunct short-circuits a deferred operand to false (not deferred-poisoning).
    No eval() or exec() is used anywhere.
    """

    def __init__(self, state: PlatformRoadmapState) -> None:
        self._state = state
        self._sorted_ids: list[str] = sorted(state._by_id.keys(), key=len, reverse=True)

    def evaluate(self, rule: str) -> tuple[_Verdict, str]:
        tokens = _tokenize(rule)
        v, r, _ = self._parse_or(tokens, 0)
        return v, r

    def _parse_or(self, tokens: list[_Token], pos: int) -> tuple[_Verdict, str, int]:
        v, r, pos = self._parse_and(tokens, pos)
        while pos < len(tokens) and tokens[pos].kind == "KEYWORD" and tokens[pos].value == "or":
            pos += 1
            v2, r2, pos = self._parse_and(tokens, pos)
            if v == "pass" or v2 == "pass":
                v, r = "pass", (r if v == "pass" else r2)
            elif v == "fail" and v2 == "fail":
                v, r = "fail", f"({r}) or ({r2})"
            else:
                v, r = "deferred", (r if v == "deferred" else r2)
        return v, r, pos

    def _parse_and(self, tokens: list[_Token], pos: int) -> tuple[_Verdict, str, int]:
        v, r, pos = self._parse_not(tokens, pos)
        while pos < len(tokens) and tokens[pos].kind == "KEYWORD" and tokens[pos].value == "and":
            pos += 1
            v2, r2, pos = self._parse_not(tokens, pos)
            if v == "fail" or v2 == "fail":
                v, r = "fail", (r if v == "fail" else r2)
            elif v == "pass" and v2 == "pass":
                v, r = "pass", f"({r}) and ({r2})"
            else:
                v, r = "deferred", (r if v == "deferred" else r2)
        return v, r, pos

    def _parse_not(self, tokens: list[_Token], pos: int) -> tuple[_Verdict, str, int]:
        if pos < len(tokens) and tokens[pos].kind == "KEYWORD" and tokens[pos].value == "not":
            pos += 1
            v, r, pos = self._parse_not(tokens, pos)
            flipped = {"pass": "fail", "fail": "pass", "deferred": "deferred"}
            return flipped.get(v, "deferred"), f"not ({r})", pos
        return self._parse_atom(tokens, pos)

    def _parse_atom(self, tokens: list[_Token], pos: int) -> tuple[_Verdict, str, int]:
        if pos >= len(tokens) or tokens[pos].kind == "EOF":
            return "fail", "empty expression", pos
        tok = tokens[pos]
        if tok.kind == "LPAREN":
            pos += 1
            v, r, pos = self._parse_or(tokens, pos)
            if pos < len(tokens) and tokens[pos].kind == "RPAREN":
                pos += 1
            return v, r, pos
        if tok.kind == "NAME":
            name = tok.value
            if pos + 1 < len(tokens) and tokens[pos + 1].kind == "LPAREN":
                return self._eval_function(tokens, pos)
            pos += 1
            if pos < len(tokens) and tokens[pos].kind == "OP":
                pos += 1
                if pos < len(tokens) and tokens[pos].kind in ("STRING", "NUMBER"):
                    rhs = tokens[pos].value
                    pos += 1
                    v, r = self._eval_field_cmp(name, rhs)
                    return v, r, pos
            return "deferred", f"unresolvable: {name}", pos
        return "fail", f"unexpected token: {tok.value}", pos + 1

    def _eval_function(self, tokens: list[_Token], pos: int) -> tuple[_Verdict, str, int]:
        name = tokens[pos].value
        pos += 2
        args: list[_Token] = []
        while pos < len(tokens) and tokens[pos].kind not in ("RPAREN", "EOF"):
            if tokens[pos].kind == "COMMA":
                pos += 1
                continue
            args.append(tokens[pos])
            pos += 1
        if pos < len(tokens) and tokens[pos].kind == "RPAREN":
            pos += 1

        if name == "tier_complete":
            tier = args[0].value if args else ""
            result = self._state.tier_complete(tier)
            return ("pass" if result else "fail"), f"tier_complete({tier!r}) = {result}", pos

        if name == "all_in_tier_with_status":
            tier = args[0].value if len(args) > 0 else ""
            status = args[1].value if len(args) > 1 else ""
            items = [i for i in self._state._doc.tier_items if i.tier == tier and i.status not in _INACTIVE_FOR_TIER]
            result = bool(items) and all(i.status == status for i in items)
            return ("pass" if result else "fail"), f"all_in_tier_with_status({tier!r}, {status!r}) = {result}", pos

        if name == "grace_period_elapsed":
            item_id = args[0].value if len(args) > 0 else ""
            try:
                days = int(args[1].value) if len(args) > 1 else 0
            except (ValueError, TypeError):
                return "fail", "grace_period_elapsed: invalid days arg", pos
            item = self._state._by_id.get(item_id)
            if item is None:
                return "fail", f"grace_period_elapsed: item {item_id!r} not found", pos
            if item.status != "complete":
                reason = f"grace_period_elapsed({item_id}, {days}): item not complete (status={item.status})"
                return "fail", reason, pos
            if not item.completed_at:
                return "deferred", f"grace_period_elapsed({item_id}, {days}): completed_at unset", pos
            try:
                completed = datetime.strptime(str(item.completed_at), "%Y-%m-%d").replace(tzinfo=timezone.utc)
                elapsed = (datetime.now(timezone.utc) - completed).days
                result = elapsed >= days
                reason = f"grace_period_elapsed({item_id}, {days}): {elapsed}d >= {days}d = {result}"
                return ("pass" if result else "fail"), reason, pos
            except (ValueError, TypeError):
                return "deferred", f"grace_period_elapsed({item_id}, {days}): cannot parse completed_at", pos

        if name == "item_field_eq":
            arg_vals = [a.value for a in args]
            return "deferred", f"item_field_eq({', '.join(arg_vals)}): runtime field (not statically resolvable)", pos

        return "fail", f"unknown helper: {name}", pos

    def _eval_field_cmp(self, field_path: str, rhs: str) -> tuple[_Verdict, str]:
        item_id, field = self._resolve_field_path(field_path)
        if item_id is None or field is None or field == "":
            return "deferred", f"{field_path}: cannot resolve to a known item id and field"
        item = self._state._by_id.get(item_id)
        if item is None:
            return "deferred", f"{field_path}: item {item_id!r} not found"
        if field == "status":
            actual = item.status
            result = actual == rhs
            return ("pass" if result else "fail"), f"{field_path} is {actual!r} (expected {rhs!r})"
        return "deferred", f"{field_path}: field {field!r} is a runtime path (not statically resolvable)"

    def _resolve_field_path(self, path: str) -> tuple[str | None, str | None]:
        """Resolve a dotted field path to (item_id, field) using longest-known-id prefix."""
        for known_id in self._sorted_ids:
            prefix = known_id + "."
            if path.startswith(prefix):
                return known_id, path[len(prefix) :]
            if path == known_id:
                return known_id, ""
        return None, None


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


class ExitCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    text: str
    status: Literal["open", "met", "rehomed"] = "open"
    met_by: str | None = None


class TierItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    tier: str
    name: str
    intent: str = ""
    depends_on: list[str] = Field(default_factory=list)
    files_in_scope: list[str] = Field(default_factory=list)
    exit_criteria: list[ExitCriterion] = Field(default_factory=list)
    related_candidate_decisions: list[str] = Field(default_factory=list)
    related_intents: list[str] | None = None
    related_decisions: list[int] | None = None
    effort: Literal["XS", "S", "M", "L", "XL"] = "S"

    @field_validator("exit_criteria", mode="before")
    @classmethod
    def _normalize_exit_criteria(cls, v: Any) -> list[Any]:
        if not isinstance(v, list):
            return v
        result: list[Any] = []
        for i, item in enumerate(v):
            if isinstance(item, str):
                result.append({"id": f"c{i + 1}", "text": item, "status": "open", "met_by": None})
            else:
                result.append(item)
        return result

    strategic: bool = False
    status: Literal["not_started", "in_progress", "complete", "reserved", "deferred_post_mvp"] = "not_started"
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
    ratified_as: str | None = None
    realization_evidence: str | None = None
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

        # (f) no not_started/in_progress item may depend directly on a deferred_post_mvp item
        deferred_ids: set[str] = {i.id for i in self.tier_items if i.status == "deferred_post_mvp"}
        if deferred_ids:
            for item in self.tier_items:
                if item.status in {"not_started", "in_progress"}:
                    for dep in item.depends_on:
                        if dep in deferred_ids:
                            raise ValueError(
                                f"tier_item '{item.id}' (status={item.status}) depends_on "
                                f"'{dep}' which is deferred_post_mvp -- no live item may depend on a parked item"
                            )

        # (g) met/rehomed criteria require a non-empty met_by
        for item in self.tier_items:
            for crit in item.exit_criteria:
                if crit.status in {"met", "rehomed"} and not crit.met_by:
                    raise ValueError(
                        f"tier_item '{item.id}' criterion '{crit.id}': status='{crit.status}' requires a non-empty met_by"
                    )

        # (h) rehomed criterion's met_by must resolve to a known tier_item id
        for item in self.tier_items:
            for crit in item.exit_criteria:
                if crit.status == "rehomed" and crit.met_by and crit.met_by not in item_ids:
                    raise ValueError(
                        f"tier_item '{item.id}' criterion '{crit.id}': "
                        f"rehomed met_by='{crit.met_by}' does not resolve to a known tier_item id"
                    )

        return self


def _item_dict(item: TierItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "tier": item.tier,
        "name": item.name,
        "effort": item.effort,
        "strategic": item.strategic,
        "user_action_required": item.user_action_required,
    }


def _pending_gating_cds_for_item(
    item: TierItem,
    pending_cds: dict[str, Any],
    cd_gates_index: dict[str, list[str]],
) -> dict[str, str]:
    """Return {cd_id: relationship} for pending CDs gating this item's completion.

    Three sources (same logic as blocked_on_cd but applicable to any item status):
      1. item.related_candidate_decisions -> relationship 'related'
      2. cd.gates contains item id or tier shortcut -> relationship 'gates'
      3. item.decision_required_before entries naming a CD id -> relationship 'decision_required_before'

    First source wins when a CD appears in multiple sources.
    """
    blocking: dict[str, str] = {}

    for cd_id in item.related_candidate_decisions:
        if cd_id in pending_cds and cd_id not in blocking:
            blocking[cd_id] = "related"

    for ref, cd_ids in cd_gates_index.items():
        if _TIER_SHORTCUT_RE.match(ref):
            match = item.tier == ref
        else:
            match = item.id == ref
        if match:
            for cd_id in cd_ids:
                if cd_id not in blocking:
                    blocking[cd_id] = "gates"

    drb = item.decision_required_before or []
    drb_entries: list[str] = drb if isinstance(drb, list) else [drb] if isinstance(drb, str) else []
    for entry in drb_entries:
        for m in _CD_REF_RE.finditer(str(entry)):
            cd_id = m.group(1)
            if cd_id in pending_cds and cd_id not in blocking:
                blocking[cd_id] = "decision_required_before"

    return blocking


def load(path: str | Path) -> RoadmapDocument:
    """Parse the YAML roadmap at path and return a validated RoadmapDocument."""
    with Path(path).open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return RoadmapDocument.model_validate(data)


def compute_followon_state(doc: RoadmapDocument, plans_dir: Path) -> dict[str, dict[str, Any]]:
    """Compute follow-on planning state for in_progress items (Decision 93: in_progress only).

    Returns dict keyed by item_id with:
      - open_criteria_count: int
      - all_plans_actioned: bool (no in-flight plan targets an open criterion of this item)
      - needs_followon_plan: bool (True iff open_criteria_count > 0 AND all_plans_actioned)
    """
    in_progress = [i for i in doc.tier_items if i.status == "in_progress"]

    open_criteria: dict[str, set[str]] = {}
    for item in in_progress:
        open_criteria[item.id] = {c.id for c in item.exit_criteria if c.status == "open"}

    covered_by_plan: dict[str, set[str]] = {item.id: set() for item in in_progress}
    if plans_dir.is_dir():
        for plan_file in sorted(plans_dir.glob("PLAN-*.yaml")):
            try:
                with plan_file.open(encoding="utf-8") as fh:
                    plan_data = yaml.safe_load(fh)
                if not isinstance(plan_data, dict):
                    continue
                closes = plan_data.get("closes_criteria") or []
                if not isinstance(closes, list):
                    continue
                for ref in closes:
                    if not isinstance(ref, str) or ":" not in ref:
                        continue
                    item_id, crit_id = ref.split(":", 1)
                    if item_id in covered_by_plan:
                        covered_by_plan[item_id].add(crit_id)
            except Exception:  # noqa: BLE001
                continue

    result: dict[str, dict[str, Any]] = {}
    for item in in_progress:
        open_set = open_criteria[item.id]
        open_count = len(open_set)
        has_in_flight = bool(open_set & covered_by_plan[item.id])
        all_actioned = not has_in_flight
        result[item.id] = {
            "open_criteria_count": open_count,
            "all_plans_actioned": all_actioned,
            "needs_followon_plan": open_count > 0 and all_actioned,
        }
    return result


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
            item.status == "complete"
            for item in self._doc.tier_items
            if item.tier == tier_name and item.status not in _INACTIVE_FOR_TIER
        )

    def resolve_depends_on(self, item_id: str) -> list[TierItem]:
        item = self._by_id.get(item_id)
        if item is None:
            return []
        result: list[TierItem] = []
        for dep in item.depends_on:
            if _TIER_SHORTCUT_RE.match(dep):
                result.extend(i for i in self._doc.tier_items if i.tier == dep and i.status not in _INACTIVE_FOR_TIER)
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

    def deferred_post_mvp_items(self) -> list[TierItem]:
        return [item for item in self._doc.tier_items if item.status == "deferred_post_mvp"]

    def active_tier(self) -> str | None:
        for tier_name in _CANONICAL_TIER_ORDER:
            tier_items = [i for i in self._doc.tier_items if i.tier == tier_name and i.status not in _INACTIVE_FOR_TIER]
            if tier_items and not all(i.status == "complete" for i in tier_items):
                return tier_name
        return None

    def _blocked_on(self, item: TierItem) -> list[str]:
        return [dep for dep in item.depends_on if not self._dep_satisfied(dep)]

    def evaluate_gates(self) -> list[dict[str, Any]]:
        """Evaluate all cross_tier_gates and return {id, name, verdict, reason} for each."""
        evaluator = GateRuleEvaluator(self)
        result: list[dict[str, Any]] = []
        for gate in self._doc.cross_tier_gates:
            verdict, reason = evaluator.evaluate(gate.rule)
            result.append({"id": gate.id, "name": gate.name, "verdict": verdict, "reason": reason})
        return result

    def blocked_on_cd(self) -> list[dict[str, Any]]:
        """Return eligible items that reference a pending candidate_decision.

        Three sources (for each eligible item):
          1. item.related_candidate_decisions -> relationship 'related'
          2. cd.gates contains item id or tier shortcut -> relationship 'gates'
          3. item.decision_required_before entries naming a CD id -> relationship 'decision_required_before'

        blocking_cds[] is sorted; relationships{} maps cd_id to the relationship type (first source wins).
        """
        pending_cds: dict[str, Any] = {cd.id: cd for cd in self._doc.candidate_decisions if cd.state == "pending"}
        if not pending_cds:
            return []

        cd_gates_index: dict[str, list[str]] = {}
        for cd_id, cd in pending_cds.items():
            for ref in cd.gates:
                cd_gates_index.setdefault(ref, []).append(cd_id)

        result: list[dict[str, Any]] = []
        for item in self.eligible_items():
            blocking = _pending_gating_cds_for_item(item, pending_cds, cd_gates_index)
            if blocking:
                result.append(
                    {
                        "id": item.id,
                        "name": item.name,
                        "blocking_cds": sorted(blocking.keys()),
                        "relationships": blocking,
                        "bootstrap_completion_exempt": item.bootstrap_completion_exempt,
                    }
                )

        return result

    def ratifiable_cds(self) -> list[dict[str, Any]]:
        """Pending CDs carrying realization_evidence -- surfaced to /orient as ready to ratify."""
        return [
            {"id": cd.id, "title": cd.title, "realization_evidence": cd.realization_evidence, "gates": cd.gates}
            for cd in self._doc.candidate_decisions
            if cd.state == "pending" and cd.realization_evidence
        ]

    def to_preflight_dict(self, plans_dir: Path | None = None) -> dict[str, Any]:
        if plans_dir is None:
            plans_dir = Path(__file__).parent.parent / "docs" / "plans"
        followon = compute_followon_state(self._doc, plans_dir)

        pending_cds: dict[str, Any] = {cd.id: cd for cd in self._doc.candidate_decisions if cd.state == "pending"}
        cd_gates_index: dict[str, list[str]] = {}
        for cd_id, cd in pending_cds.items():
            for ref in cd.gates:
                cd_gates_index.setdefault(ref, []).append(cd_id)

        def _in_progress_dict(item: TierItem) -> dict[str, Any]:
            d = _item_dict(item)
            state = followon.get(item.id, {})
            d["open_criteria_count"] = state.get("open_criteria_count", 0)
            d["all_plans_actioned"] = state.get("all_plans_actioned", True)
            d["needs_followon_plan"] = state.get("needs_followon_plan", False)
            if item.bootstrap_completion_exempt:
                d["completion_blocked_on_cd"] = []
            else:
                blocking = _pending_gating_cds_for_item(item, pending_cds, cd_gates_index)
                d["completion_blocked_on_cd"] = sorted(blocking.keys())
            return d

        return {
            "next_eligible": [_item_dict(i) for i in self.eligible_items() if not i.strategic],
            "in_progress": [_in_progress_dict(i) for i in self.in_progress_items()],
            "blocked": [{**_item_dict(i), "blocked_on": self._blocked_on(i)} for i in self.compute_blocked()],
            "strategic_pending": [_item_dict(i) for i in self.strategic_pending_items()],
            "deferred_post_mvp": [_item_dict(i) for i in self.deferred_post_mvp_items()],
            "active_tier": self.active_tier(),
            "blocked_on_cd": self.blocked_on_cd(),
            "ratifiable_cds": self.ratifiable_cds(),
            "gate_evaluations": self.evaluate_gates(),
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
            "deferred_post_mvp": [],
            "active_tier": None,
            "blocked_on_cd": [],
            "ratifiable_cds": [],
            "gate_evaluations": [],
        }

    plans_dir = Path(yaml_path).parent / "plans"
    state = PlatformRoadmapState(doc)
    result = state.to_preflight_dict(plans_dir=plans_dir)

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
