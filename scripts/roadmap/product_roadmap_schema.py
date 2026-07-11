"""Pydantic schema models and gate-rule parser for docs/ROADMAP-PRODUCT.yaml."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Module-level constants (consumed only by model validators in this file)
# ---------------------------------------------------------------------------

_SUPPORTED_VERSIONS: frozenset[int] = frozenset({1})
_OPS_DECISIONS_RE = re.compile(r"^ops_decisions:dec-\d+$")


# ---------------------------------------------------------------------------
# GateRuleParser (self-contained; do NOT import from platform_roadmap so
# PRODUCT validation still works when PLATFORM fails to load)
# ---------------------------------------------------------------------------


class GateRuleParser:
    """Validates gate-rule expressions against the gate_helpers table.

    Tokenises function calls only (name + arity). Never evaluates.
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


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class GateHelper(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    arity: int
    params: list[dict[str, Any]] = Field(default_factory=list)
    returns: str = "bool"
    semantics: str = ""
    scope: Literal["product_local", "inherited_from_platform"] = "product_local"


class DocumentMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")
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


class FourLayerEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    layer: str
    name: str
    responsibility: str = ""
    interface: str = ""
    inputs: str = ""
    outputs: str = ""
    contract_refs: list[dict[str, Any]] = Field(default_factory=list)
    contains_risk_constraints: bool = False
    contains_pretrade_gates: bool = False
    notes: str = ""


# Prose-heavy descriptive blocks: presence-checking only, extra ignored
class CurrentState(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ThreeTierData(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Environments(BaseModel):
    model_config = ConfigDict(extra="ignore")


class EvaluationMetrics(BaseModel):
    model_config = ConfigDict(extra="ignore")


class MinimumViableV1(BaseModel):
    model_config = ConfigDict(extra="ignore")


class PromotionFunnel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class NorthStar(BaseModel):
    model_config = ConfigDict(extra="ignore")
    principles: list[Any] = Field(default_factory=list)


class ContractGate(BaseModel):
    # 'class' is a Python keyword; use alias
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    path: str
    contract_class: Literal["A", "B", "C", "D"] = Field(alias="class")
    contract_version: int


class FivePropertyAttestation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attestation: str
    cites: str


class FivePropertyTest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parameterised: FivePropertyAttestation
    versioned: FivePropertyAttestation
    composable: FivePropertyAttestation
    observable: FivePropertyAttestation
    evaluable: FivePropertyAttestation


class FivePropertyWaiver(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str
    will_attest_when: str

    @model_validator(mode="after")
    def _check_non_empty(self) -> "FivePropertyWaiver":
        if not self.reason.strip():
            raise ValueError("reason must be non-empty")
        if not self.will_attest_when.strip():
            raise ValueError("will_attest_when must be non-empty")
        return self


class TierItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    tier: str
    layer: str
    name: str
    intent: str = ""
    depends_on: list[str] = Field(default_factory=list)
    cross_roadmap_depends_on: list[str] = Field(default_factory=list)
    contract_gates: list[ContractGate] = Field(default_factory=list)
    environment_scope: list[str] = Field(default_factory=list)
    effort: Literal["XS", "S", "M", "L", "XL"] = "S"
    strategic: bool = False
    status: Literal["not_started", "in_progress", "complete", "reserved"] = "not_started"
    validation_lens: str = ""
    five_property_test: FivePropertyTest | None = None
    five_property_test_waiver: FivePropertyWaiver | None = None
    deferred: bool = False
    deferred_note: str | None = None
    owning_layer: str | None = None


class CandidateDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    detail: str = ""
    gates: list[str] = Field(default_factory=list)
    state: str = "pending"
    pivot_reference: str | None = None
    decision_required_before: str | None = None


class ResearchPoolDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    pivot_reference: str = ""
    pivot_quote: str = ""
    why_not_ratified_now: str = ""
    proposed_resolution: str = ""
    affected_tier_items: list[str] = Field(default_factory=list)


class CrossTierGate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    rule: str
    rationale: str = ""
    helpers_required: list[str] = Field(default_factory=list)


class RetiredItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_section: str = ""
    source_bullet_ids: list[Any] = Field(default_factory=list)
    reason: str = ""


class OutOfProductScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_bullet_id: Any = None
    text: str = ""
    disposition: str = ""
    note: str = ""


class OpenQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    question: str = ""
    auditor_default_recommendation: str = ""
    consequences_if_resolved_differently: str = ""


class KnownGap(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    gap: str = ""
    notes: str = ""


class KnownPlatformGap(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    description: str = ""
    intended_platform_tier_item: str

    @field_validator("id")
    @classmethod
    def _check_id_format(cls, v: str) -> str:
        if not re.match(r"^GAP-[a-z0-9-]+$", v):
            raise ValueError(f"id must match ^GAP-[a-z0-9-]+$: got '{v}'")
        return v
