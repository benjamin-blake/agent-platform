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

from datetime import date, datetime, timezone
from typing import Any

import yaml
from pydantic import ValidationError

from scripts.contracts import ContractValidationError, validate_status_transition
from scripts.contracts_schema import ChangeClass, ContractClass, ContractDocument, ContractStatus

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
    """Return error strings for description/semantics changes lacking a valid amendment entry.

    Category 6 (INTENT Invariant 3/4, Part 9I): any change to contract.description or a field's
    description/semantics must be accompanied by a NEW amendment_log[] entry whose change_class
    and semantic_break are consistent with the change -- either change_class: prose_improvement
    with semantic_break: false (pure documentation polish), or any other change_class with
    semantic_break: true (a genuine redefinition through the ritual). Both a bare diff (no new
    entry) and a mislabelled entry (prose_improvement with semantic_break: true, or a non-prose
    change_class with semantic_break: false) are rejected.
    """
    errors: list[str] = []

    base_contract_log = [e.model_dump() for e in (base_doc.amendment_log or [])]
    head_contract_log = [e.model_dump() for e in (head_doc.amendment_log or [])]
    if base_doc.contract.description != head_doc.contract.description:
        err = _amendment_error_for_change("contract description", base_contract_log, head_contract_log)
        if err is not None:
            errors.append(err)

    base_fields = base_doc.fields or {}
    head_fields = head_doc.fields or {}
    for name, head_spec in head_fields.items():
        base_spec = base_fields.get(name)
        if base_spec is None:
            continue
        attr_changed = any(getattr(base_spec, attr) != getattr(head_spec, attr) for attr in ("description", "semantics"))
        if attr_changed:
            base_field_log = [e.model_dump() for e in (base_spec.amendment_log or [])]
            head_field_log = [e.model_dump() for e in (head_spec.amendment_log or [])]
            err = _amendment_error_for_change(f"field {name!r} description/semantics", base_field_log, head_field_log)
            if err is not None:
                errors.append(err)
    return errors


def _amendment_error_for_change(
    subject: str,
    base_log: list[dict[str, Any]],
    head_log: list[dict[str, Any]],
) -> str | None:
    """Return a category-6 error for ``subject`` if it changed without a valid accompanying
    amendment_log[] entry, else None.

    A new entry is a valid accompaniment iff it pairs change_class: prose_improvement with
    semantic_break: false, or any other change_class with semantic_break: true (INTENT
    Invariant 3/4: prose_improvement is the only non-break path for a prose change, and a
    redefinition must set semantic_break: true).
    """
    new_entries = [e for e in head_log if e not in base_log]
    if not new_entries:
        return f"{subject} changed but no new amendment_log[] entry was added (category 6)"
    if not any(_amendment_entry_consistent(e) for e in new_entries):
        return (
            f"{subject} changed but no new amendment_log[] entry pairs change_class: prose_improvement "
            f"with semantic_break: false, or another change_class with semantic_break: true (category 6)"
        )
    return None


def _amendment_entry_consistent(entry: dict[str, Any]) -> bool:
    """True iff a single amendment entry's change_class/semantic_break pairing is valid for a
    description/semantics diff: prose_improvement XOR semantic_break (INTENT Invariant 3/4).

    prose_improvement (which by definition does not change meaning) requires semantic_break:
    false; any other change_class on a description/semantics diff requires semantic_break: true.
    """
    is_prose = entry.get("change_class") == ChangeClass.prose_improvement
    semantic_break = bool(entry.get("semantic_break"))
    return is_prose != semantic_break


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


def default_provisional_metrics(doc: ContractDocument, now: datetime | None = None) -> dict[str, Any]:
    """Compute the deterministic, credential-free days-since metric for a provisional_v0 contract.

    Reads provisional_v0.first_production_invocation_date (ISO date string) and returns
    {"days_since_first_production_invocation": <int>} using (now or utcnow()).date() minus that
    date, floored at 0. Returns {} when the contract is not provisional_v0, the field is absent,
    or the field is unparseable (fail-safe: absent metric means the condition cannot fire).
    Supplies no "production_invocations" key -- that metric stays dormant pending telemetry (T2.36).
    """
    if doc.contract.status != ContractStatus.provisional_v0:
        return {}
    prov = doc.contract.provisional_v0
    if not isinstance(prov, dict):
        return {}
    first_date_str = prov.get("first_production_invocation_date")
    if not isinstance(first_date_str, str):
        return {}
    try:
        first_date = date.fromisoformat(first_date_str)
    except ValueError:
        return {}
    today = (now or datetime.now(timezone.utc)).date()
    days_since = max(0, (today - first_date).days)
    return {"days_since_first_production_invocation": days_since}


def check_re_ratification_trigger(doc: ContractDocument) -> list[str]:
    """Return error strings for a malformed provisional_v0 re_ratification_trigger.

    For provisional_v0 contracts, re_ratification_trigger.first_of must be a non-empty list of
    strings each parseable via _parse_condition; any condition referencing
    days_since_first_production_invocation requires provisional_v0.first_production_invocation_date
    to be present and a valid ISO date. Non-provisional contracts, or ones missing the
    provisional_v0/trigger block, return [] -- this check only gates the trigger's own well-formedness.
    """
    if doc.contract.status != ContractStatus.provisional_v0:
        return []
    prov = doc.contract.provisional_v0
    if not isinstance(prov, dict):
        return []
    trigger = prov.get("re_ratification_trigger")
    if not isinstance(trigger, dict):
        return []
    first_of = trigger.get("first_of")
    if not isinstance(first_of, list) or not first_of:
        return [f"re_ratification_trigger.first_of must be a non-empty list, got {first_of!r}"]

    errors: list[str] = []
    needs_date = False
    for condition in first_of:
        parsed = _parse_condition(condition) if isinstance(condition, str) else None
        if parsed is None:
            errors.append(f"re_ratification_trigger condition unparseable: {condition!r}")
            continue
        if parsed[0] == "days_since_first_production_invocation":
            needs_date = True

    if needs_date:
        first_date_str = prov.get("first_production_invocation_date")
        if not isinstance(first_date_str, str):
            errors.append(
                "re_ratification_trigger references days_since_first_production_invocation but "
                "provisional_v0.first_production_invocation_date is missing"
            )
        else:
            try:
                date.fromisoformat(first_date_str)
            except ValueError:
                errors.append(f"provisional_v0.first_production_invocation_date is not a valid ISO date: {first_date_str!r}")
    return errors
