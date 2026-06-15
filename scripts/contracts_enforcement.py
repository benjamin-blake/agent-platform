"""Contract ritual enforcement helpers for the CI drift gate and preflight hook (T-1.12e+f).

Reusable, import-safe domain logic shared by validate.py (validate_contract_drift) and
session_preflight.py (provisional-contract scan).  No module-level I/O; raises nothing
at import time (AGENTS.md Safety; mirrors contracts.py / contracts_schema.py).

Categories enforced here (CD.25 / INTENT Part 9I):
  2  -- inline Class-A field missing description/semantics/populated_by/dq_intent
  6  -- description/semantics change with no accompanying amendment_log[] entry
  7  -- status transition outside Invariant-6 state machine

Structural categories (1, 3, 4, 5, 8) are already raised by contracts.load_contract and
contracts.resolve_refs; this module does not re-implement them.
"""

from __future__ import annotations

from typing import Any

import yaml
from pydantic import ValidationError

from scripts.contracts import ContractValidationError, validate_status_transition
from scripts.contracts_schema import ContractClass, ContractDocument, ContractStatus

_REQUIRED_INLINE_KEYS: tuple[str, ...] = ("description", "semantics", "populated_by", "dq_intent")

_CONDITION_LHS: frozenset[str] = frozenset(
    {
        "production_invocations",
        "days_since_first_production_invocation",
    }
)


def check_required_inline_fields(doc: ContractDocument) -> list[str]:
    """Return error strings for inline Class-A fields missing required descriptive keys.

    Category 2: every inline (non-$ref) field on a Class A contract must carry
    description, semantics, populated_by, and dq_intent.
    """
    if doc.contract.class_ != ContractClass.A:
        return []
    errors: list[str] = []
    for name, spec in (doc.fields or {}).items():
        if spec.ref is not None:
            continue
        for key in _REQUIRED_INLINE_KEYS:
            if getattr(spec, key, None) is None:
                errors.append(f"field {name!r}: inline Class-A field missing required key '{key}' (category 2)")
    return errors


def check_amendment_for_diff(base_doc: ContractDocument, head_doc: ContractDocument) -> list[str]:
    """Return error strings for description/semantics changes without a new amendment_log entry.

    Category 6: any change to contract.description or a field's description/semantics must
    be accompanied by a new amendment_log[] entry added in this diff.
    """
    errors: list[str] = []

    base_contract_log = [e.model_dump() for e in (base_doc.amendment_log or [])]
    head_contract_log = [e.model_dump() for e in (head_doc.amendment_log or [])]

    if base_doc.contract.description != head_doc.contract.description:
        new_entries = [e for e in head_contract_log if e not in base_contract_log]
        if not new_entries:
            errors.append("contract description changed but no new amendment_log[] entry was added (category 6)")

    base_fields = base_doc.fields or {}
    head_fields = head_doc.fields or {}
    for name, head_spec in head_fields.items():
        base_spec = base_fields.get(name)
        if base_spec is None:
            continue
        base_field_log = [e.model_dump() for e in (base_spec.amendment_log or [])]
        head_field_log = [e.model_dump() for e in (head_spec.amendment_log or [])]
        attr_changed = any(getattr(base_spec, attr) != getattr(head_spec, attr) for attr in ("description", "semantics"))
        if attr_changed:
            new_entries = [e for e in head_field_log if e not in base_field_log]
            if not new_entries:
                errors.append(
                    f"field {name!r}: description/semantics changed but no new amendment_log[] entry on the field (category 6)"
                )
    return errors


def check_status_transition(base_doc: ContractDocument, head_doc: ContractDocument) -> list[str]:
    """Return error strings for a status change that violates Invariant-6 (category 7).

    Delegates to contracts.validate_status_transition when the status changed.
    Returns [] when the status is unchanged.
    """
    old_status = base_doc.contract.status.value
    new_status = head_doc.contract.status.value
    if old_status == new_status:
        return []
    try:
        validate_status_transition(old_status, new_status)
        return []
    except ContractValidationError as exc:
        return [f"{exc} (category 7)"]


def _load_contract_from_text(text: str) -> ContractDocument:
    """Parse YAML text into a ContractDocument without a temp file.

    Used to load git-show base content inside validate_contract_drift.
    Raises ContractValidationError on bad YAML or Pydantic schema violation.
    """
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ContractValidationError(f"invalid YAML in base content: {exc}") from exc
    if not isinstance(data, dict):
        raise ContractValidationError(f"base contract content must be a YAML mapping, got {type(data).__name__}")
    try:
        return ContractDocument.model_validate(data)
    except ValidationError as exc:
        raise ContractValidationError(f"schema validation failed for base content: {exc}") from exc


def _parse_condition(condition: str) -> tuple[str, int] | None:
    """Parse a trigger condition string of the form 'lhs >= threshold'.

    Returns (lhs, threshold) on success; None if the string does not match the
    fixed vocabulary.  Only '>=' is supported.  No eval/exec -- explicit token comparison.
    """
    parts = condition.split(">=", 1)
    if len(parts) != 2:
        return None
    lhs = parts[0].strip()
    rhs = parts[1].strip()
    if lhs not in _CONDITION_LHS:
        return None
    try:
        return lhs, int(rhs)
    except ValueError:
        return None


def evaluate_provisional_trigger(
    doc: ContractDocument,
    metrics: dict[str, Any] | None = None,
) -> tuple[bool, str | None]:
    """Evaluate re_ratification_trigger first_of conditions against a metrics mapping.

    Returns (met, firing_condition).  ``met`` is True when at least one condition fires;
    ``firing_condition`` is the first condition string that evaluated True.

    When ``metrics`` is None or a required metric key is absent, conditions that depend on
    it are treated as unmet (fail-safe: no false positives from missing data).

    Returns (False, None) for contracts that are not provisional_v0 or lack the trigger block.
    """
    if doc.contract.status != ContractStatus.provisional_v0:
        return False, None

    prov = doc.contract.provisional_v0
    if not isinstance(prov, dict):
        return False, None

    trigger = prov.get("re_ratification_trigger")
    if not isinstance(trigger, dict):
        return False, None

    first_of = trigger.get("first_of")
    if not isinstance(first_of, list):
        return False, None

    effective_metrics = metrics or {}
    for condition in first_of:
        if not isinstance(condition, str):
            continue
        parsed = _parse_condition(condition)
        if parsed is None:
            continue
        lhs, threshold = parsed
        value = effective_metrics.get(lhs)
        if value is None:
            continue
        try:
            if int(value) >= threshold:
                return True, condition
        except (ValueError, TypeError):
            continue

    return False, None
