"""Static contract-validation concern of scripts/contracts_enforcement.py (rec-2709 Wave 11).

Covers check_required_inline_fields, check_amendment_for_diff, check_status_transition, and
_load_contract_from_text. Split from tests/test_contracts_enforcement.py (VERBATIM move).
"""

from __future__ import annotations

import textwrap

import pytest

from scripts.contracts import ContractValidationError
from scripts.contracts_enforcement import (
    _load_contract_from_text,
    check_amendment_for_diff,
    check_required_inline_fields,
    check_status_transition,
)
from scripts.contracts_schema import (
    AmendmentLogEntry,
    ChangeClass,
    ContractClass,
    ContractDocument,
    ContractMeta,
    ContractStatus,
    FieldSpec,
)
from tests.fixtures.contracts_enforcement import _make_class_a_doc


def _make_class_b_doc() -> ContractDocument:
    from scripts.contracts_schema import VerbSpec  # noqa: PLC0415

    return ContractDocument(
        contract=ContractMeta(
            id="test-b",
            **{"class": ContractClass.B},
            contract_version=1,
            status=ContractStatus.draft,
        ),
        verbs={"do_thing": VerbSpec()},
    )


def _amendment_entry(
    *,
    change_class: ChangeClass = ChangeClass.prose_improvement,
    semantic_break: bool = False,
) -> AmendmentLogEntry:
    return AmendmentLogEntry(date="2026-01-01", semantic_break=semantic_break, change_class=change_class)


class TestCheckRequiredInlineFields:
    def test_passes_for_class_b(self) -> None:
        doc = _make_class_b_doc()
        assert check_required_inline_fields(doc) == []

    def test_passes_for_fully_populated_class_a(self) -> None:
        doc = _make_class_a_doc()
        assert check_required_inline_fields(doc) == []

    def test_skips_ref_fields(self) -> None:
        fields = {"f1": FieldSpec(**{"$ref": "other.yaml#/contract/fields/f1"})}
        doc = _make_class_a_doc(fields=fields)
        assert check_required_inline_fields(doc) == []

    def test_flags_missing_description(self) -> None:
        fields = {
            "f1": FieldSpec(
                type="string",
                nullable=False,
                semantics="The meaning",
                populated_by="writer",
                dq_intent={"not_null": {"enforced": True}},
            )
        }
        doc = _make_class_a_doc(fields=fields)
        errors = check_required_inline_fields(doc)
        assert any("description" in e for e in errors)
        assert any("category 2" in e for e in errors)

    def test_flags_missing_semantics(self) -> None:
        fields = {
            "f1": FieldSpec(
                type="string",
                nullable=False,
                description="A field",
                populated_by="writer",
                dq_intent={"not_null": {"enforced": True}},
            )
        }
        doc = _make_class_a_doc(fields=fields)
        errors = check_required_inline_fields(doc)
        assert any("semantics" in e for e in errors)

    def test_flags_missing_populated_by(self) -> None:
        fields = {
            "f1": FieldSpec(
                type="string",
                nullable=False,
                description="A field",
                semantics="The meaning",
                dq_intent={"not_null": {"enforced": True}},
            )
        }
        doc = _make_class_a_doc(fields=fields)
        errors = check_required_inline_fields(doc)
        assert any("populated_by" in e for e in errors)

    def test_flags_missing_dq_intent(self) -> None:
        fields = {
            "f1": FieldSpec(
                type="string",
                nullable=False,
                description="A field",
                semantics="The meaning",
                populated_by="writer",
            )
        }
        doc = _make_class_a_doc(fields=fields)
        errors = check_required_inline_fields(doc)
        assert any("dq_intent" in e for e in errors)

    def test_only_ref_fields_yields_no_errors(self) -> None:
        # A Class A doc whose only field is a $ref carries no inline fields to check.
        fields = {"f1": FieldSpec(**{"$ref": "other.yaml#/contract/fields/f1"})}
        doc = _make_class_a_doc(fields=fields)
        assert check_required_inline_fields(doc) == []


class TestCheckAmendmentForDiff:
    def test_no_changes_no_errors(self) -> None:
        doc = _make_class_a_doc()
        assert check_amendment_for_diff(doc, doc) == []

    def test_description_change_without_log_entry_errors(self) -> None:
        base = _make_class_a_doc(description="Old description")
        head = _make_class_a_doc(description="New description")
        errors = check_amendment_for_diff(base, head)
        assert any("description changed" in e for e in errors)
        assert any("category 6" in e for e in errors)

    def test_description_change_with_new_log_entry_passes(self) -> None:
        base = _make_class_a_doc(description="Old description", amendment_log=[])
        head = _make_class_a_doc(description="New description", amendment_log=[_amendment_entry()])
        assert check_amendment_for_diff(base, head) == []

    def test_field_description_change_without_log_errors(self) -> None:
        base_fields = {
            "f1": FieldSpec(
                type="string",
                nullable=False,
                description="Old field description",
                semantics="The meaning",
                populated_by="writer",
                dq_intent={"not_null": {"enforced": True}},
            )
        }
        head_fields = {
            "f1": FieldSpec(
                type="string",
                nullable=False,
                description="New field description",
                semantics="The meaning",
                populated_by="writer",
                dq_intent={"not_null": {"enforced": True}},
            )
        }
        base = _make_class_a_doc(fields=base_fields)
        head = _make_class_a_doc(fields=head_fields)
        errors = check_amendment_for_diff(base, head)
        assert any("f1" in e for e in errors)
        assert any("category 6" in e for e in errors)

    def test_field_description_change_with_new_log_passes(self) -> None:
        base_fields = {
            "f1": FieldSpec(
                type="string",
                nullable=False,
                description="Old",
                semantics="The meaning",
                populated_by="writer",
                dq_intent={},
            )
        }
        head_fields = {
            "f1": FieldSpec(
                type="string",
                nullable=False,
                description="New",
                semantics="The meaning",
                populated_by="writer",
                dq_intent={},
                amendment_log=[_amendment_entry()],
            )
        }
        base = _make_class_a_doc(fields=base_fields)
        head = _make_class_a_doc(fields=head_fields)
        assert check_amendment_for_diff(base, head) == []

    def test_field_semantics_change_without_log_errors(self) -> None:
        base_fields = {
            "f1": FieldSpec(
                type="string",
                nullable=False,
                description="A field",
                semantics="Old semantics",
                populated_by="writer",
                dq_intent={},
            )
        }
        head_fields = {
            "f1": FieldSpec(
                type="string",
                nullable=False,
                description="A field",
                semantics="New semantics",
                populated_by="writer",
                dq_intent={},
            )
        }
        base = _make_class_a_doc(fields=base_fields)
        head = _make_class_a_doc(fields=head_fields)
        errors = check_amendment_for_diff(base, head)
        assert any("f1" in e for e in errors)

    def test_new_field_in_head_skipped(self) -> None:
        # base has only f1; head adds new_field (absent on base) -- the new field is skipped
        # (no prior version to diff against) so no category-6 error fires.
        base = _make_class_a_doc()
        head_fields = {
            "f1": FieldSpec(
                type="string",
                nullable=False,
                description="A field",
                semantics="The meaning",
                populated_by="writer",
                dq_intent={"not_null": {"enforced": True}},
            ),
            "new_field": FieldSpec(
                type="string",
                nullable=False,
                description="Brand new",
                semantics="Something",
                populated_by="writer",
                dq_intent={},
            ),
        }
        head = _make_class_a_doc(fields=head_fields)
        assert check_amendment_for_diff(base, head) == []

    def test_prose_improvement_with_semantic_break_is_mislabelled(self) -> None:
        # prose_improvement (no meaning change) paired with semantic_break: true is inconsistent.
        base = _make_class_a_doc(description="Old", amendment_log=[])
        head = _make_class_a_doc(
            description="New",
            amendment_log=[_amendment_entry(change_class=ChangeClass.prose_improvement, semantic_break=True)],
        )
        errors = check_amendment_for_diff(base, head)
        assert any("category 6" in e for e in errors)
        assert any("semantic_break" in e for e in errors)

    def test_nonprose_change_class_without_semantic_break_is_mislabelled(self) -> None:
        # A non-prose change_class on a description diff must set semantic_break: true.
        base = _make_class_a_doc(description="Old", amendment_log=[])
        head = _make_class_a_doc(
            description="New",
            amendment_log=[_amendment_entry(change_class=ChangeClass.type_widen, semantic_break=False)],
        )
        errors = check_amendment_for_diff(base, head)
        assert any("category 6" in e for e in errors)

    def test_redefinition_with_semantic_break_passes(self) -> None:
        # A genuine redefinition: any non-prose change_class with semantic_break: true is accepted.
        base = _make_class_a_doc(description="Old", amendment_log=[])
        head = _make_class_a_doc(
            description="New",
            amendment_log=[_amendment_entry(change_class=ChangeClass.type_widen, semantic_break=True)],
        )
        assert check_amendment_for_diff(base, head) == []

    def test_field_semantics_change_with_prose_improvement_passes(self) -> None:
        # Field-level prose_improvement + semantic_break: false is the valid non-break prose path.
        base_fields = {
            "f1": FieldSpec(
                type="string",
                nullable=False,
                description="A field",
                semantics="Old semantics",
                populated_by="writer",
                dq_intent={},
            )
        }
        head_fields = {
            "f1": FieldSpec(
                type="string",
                nullable=False,
                description="A field",
                semantics="New semantics",
                populated_by="writer",
                dq_intent={},
                amendment_log=[_amendment_entry(change_class=ChangeClass.prose_improvement, semantic_break=False)],
            )
        }
        base = _make_class_a_doc(fields=base_fields)
        head = _make_class_a_doc(fields=head_fields)
        assert check_amendment_for_diff(base, head) == []


class TestCheckStatusTransition:
    def test_no_status_change_no_error(self) -> None:
        doc = _make_class_a_doc(status=ContractStatus.draft)
        assert check_status_transition(doc, doc) == []

    def test_valid_transition_passes(self) -> None:
        base = _make_class_a_doc(status=ContractStatus.draft)
        head = _make_class_a_doc(status=ContractStatus.ratified)
        assert check_status_transition(base, head) == []

    def test_invalid_transition_errors(self) -> None:
        base = _make_class_a_doc(status=ContractStatus.draft)
        head = _make_class_a_doc(status=ContractStatus.deprecated)
        errors = check_status_transition(base, head)
        assert errors
        assert any("category 7" in e for e in errors)

    def test_deprecated_outgoing_forbidden(self) -> None:
        base = _make_class_a_doc(status=ContractStatus.deprecated)
        head = _make_class_a_doc(status=ContractStatus.ratified)
        errors = check_status_transition(base, head)
        assert errors


class TestLoadContractFromText:
    def test_valid_yaml_returns_document(self) -> None:
        yaml_text = textwrap.dedent("""
            contract:
              id: load-test
              class: A
              contract_version: 1
              status: draft
            fields:
              f1:
                type: string
                nullable: false
                description: A field
                semantics: The meaning
                populated_by: writer
                dq_intent:
                  not_null:
                    enforced: true
        """).strip()
        doc = _load_contract_from_text(yaml_text)
        assert doc.contract.id == "load-test"

    def test_invalid_yaml_raises(self) -> None:
        with pytest.raises(ContractValidationError, match="invalid YAML"):
            _load_contract_from_text("{bad: [unclosed")

    def test_non_mapping_raises(self) -> None:
        with pytest.raises(ContractValidationError, match="must be a YAML mapping"):
            _load_contract_from_text("- just\n- a\n- list\n")

    def test_schema_violation_raises(self) -> None:
        with pytest.raises(ContractValidationError, match="schema validation failed"):
            _load_contract_from_text("contract:\n  id: bad\n  class: Z\n  contract_version: 1\n  status: draft\n")
