"""Canonical Pydantic v2 schema for the pre-codegen contract ritual (T-1.12 subset d).

Models the Class A/B/C `docs/contracts/{name}.yaml` ritual contract shape defined in
docs/INTENT-pre-codegen-contract-ratification.md Parts 3C-3E and Part 4 Invariants 1-6.

Split out from scripts/contracts.py (the loader/resolver public API) to keep each module
under the 500-SLOC gate (Decision 43). The loader imports these models; the subset-(e) CI
drift gate imports the ContractStatus / ChangeClass / ContractClass enums from HERE, not
from contracts.py.

Import safety: defining enums and models performs no I/O and raises nothing at import time.
All validation is deferred to explicit model construction inside load_contract / resolve_refs.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContractClass(str, Enum):
    """The three ritual contract classes (INTENT Part 2A)."""

    A = "A"
    B = "B"
    C = "C"


class ContractStatus(str, Enum):
    """Contract lifecycle status enum (INTENT Part 4 Invariant 6)."""

    draft = "draft"
    ratified = "ratified"
    provisional_v0 = "provisional_v0"
    deprecated = "deprecated"
    superseded = "superseded"


class ChangeClass(str, Enum):
    """Closed 8-value amendment vocabulary (INTENT Part 4 Invariant 3)."""

    field_add = "field_add"
    not_null_tighten = "not_null_tighten"
    type_widen = "type_widen"
    join_add = "join_add"
    prose_improvement = "prose_improvement"
    governance_note_add = "governance_note_add"
    accepted_values_narrow = "accepted_values_narrow"
    accepted_values_extend = "accepted_values_extend"


class AmendmentLogEntry(BaseModel):
    """One field-level (or contract-level) amendment audit entry (INTENT Invariant 3)."""

    model_config = ConfigDict(extra="forbid")

    date: str
    semantic_break: bool
    change_class: ChangeClass
    summary: str | None = None
    migration_story: str | None = None


class FieldSpec(BaseModel):
    """A single contract field, either defined inline or referenced via `$ref` (Invariant 5).

    Inline (Class A canonical) fields carry type/iceberg_type/nullable/description/semantics
    plus dq_intent. Referencing fields carry `$ref` (aliased to `ref`) plus only the additive
    `*_local` overrides; the resolver (scripts/contracts.py::resolve_refs) rejects a field that
    carries both a `$ref` and an inline definition.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: str | None = None
    iceberg_type: str | None = None
    nullable: bool | None = None
    description: str | None = None
    semantics: str | None = None
    populated_by: str | None = None
    write_time_validation: str | None = None
    dq_intent: dict[str, Any] | None = None
    governance_notes: str | None = None
    ref: str | None = Field(default=None, alias="$ref")
    dq_intent_local: dict[str, Any] | None = None
    governance_notes_local: str | None = None
    joins: list[str] | None = None
    amendment_log: list[AmendmentLogEntry] = Field(default_factory=list)
    derivation: dict[str, Any] | None = None


class VerbSpec(BaseModel):
    """A single Class B verb entry (INTENT Part 3D)."""

    model_config = ConfigDict(extra="forbid")

    payload_schema_ref: str | None = None
    response_codes: dict[int, str] | None = None
    typed_errors: dict[str, str] | None = None


class ContractGovernance(BaseModel):
    """Governance block superset across Class A/B/C (INTENT Parts 3C-3E).

    A single closed model rather than a per-class union: each class populates the subset of
    fields relevant to it. extra="forbid" still rejects keys outside this superset.
    """

    model_config = ConfigDict(extra="forbid")

    table_class: str | None = None
    partition_by: str | None = None
    dedup_view: str | None = None
    write_path: str | None = None
    id_allocator: str | None = None
    merge_key: str | None = None
    auth_type: str | None = None
    principal_classes: list[str] | None = None
    admin_only_features: list[str] | None = None
    registry_path: str | None = None
    injection_path: str | None = None
    validation_path: str | None = None
    human_initiated_value: str | None = None


class ContractMeta(BaseModel):
    """The top-level `contract:` mapping (INTENT Parts 3C-3E)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    class_: ContractClass = Field(alias="class")
    contract_version: int
    status: ContractStatus
    ratified_at: str | None = None
    ratified_via: str | None = None
    description: str | None = None
    projects_to: dict[str, Any] | None = None
    governance: ContractGovernance | None = None
    amendment_policy: dict[str, Any] | None = None
    write_payload_projection: dict[str, Any] | None = None
    provisional_v0: dict[str, Any] | None = None


class ContractDocument(BaseModel):
    """A full ritual contract document (INTENT Parts 3C-3E).

    Class A carries `fields`; Class B carries `verbs`; Class C is concept-shaped (neither
    `fields` nor `verbs`, with a top-level `governance` block). The class-conditional shape
    is enforced by the model validator below.
    """

    model_config = ConfigDict(extra="forbid")

    contract: ContractMeta
    fields: dict[str, FieldSpec] | None = None
    verbs: dict[str, VerbSpec] | None = None
    governance: ContractGovernance | None = None
    allowed_values: Any | None = None
    joins_using_this_key: list[str] | None = None
    governance_notes: str | None = None
    audit_invariants: list[str] | None = None
    amendment_log: list[AmendmentLogEntry] | None = None
    previous_versions: list[Any] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_class_shape(self) -> ContractDocument:
        cls = self.contract.class_
        if cls is ContractClass.A:
            if not self.fields:
                raise ValueError("Class A contract must define a non-empty `fields` mapping")
            if self.verbs is not None:
                raise ValueError("Class A contract must not define `verbs`")
        elif cls is ContractClass.B:
            if not self.verbs:
                raise ValueError("Class B contract must define a non-empty `verbs` mapping")
            if self.fields is not None:
                raise ValueError("Class B contract must not define `fields`")
        else:  # ContractClass.C -- concept-shaped (not verb-shaped). MAY own the canonical
            # cross-system field definitions that Class A contracts reference via $ref
            # (Invariant 5: a shared field is defined once, in the Class C contract).
            if self.verbs is not None:
                raise ValueError("Class C contract must not define `verbs`")
        return self
