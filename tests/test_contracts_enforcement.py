"""Unit tests for scripts/contracts_enforcement.py (T-1.12 subset e).

Covers every helper: each rejection category fires and passes correctly, the safe
condition-string parser handles valid/garbage inputs, and evaluate_provisional_trigger
returns met/unmet verdicts for injected metrics.  100% per-file coverage of the new module.
"""

from __future__ import annotations

import textwrap

import pytest

from scripts.contracts import ContractValidationError
from scripts.contracts_enforcement import (
    _load_contract_from_text,
    _parse_condition,
    check_amendment_for_diff,
    check_required_inline_fields,
    check_status_transition,
    evaluate_provisional_trigger,
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


def _make_class_a_doc(
    *,
    contract_id: str = "test-a",
    status: ContractStatus = ContractStatus.draft,
    description: str | None = "A contract",
    fields: dict | None = None,
    amendment_log: list[AmendmentLogEntry] | None = None,
) -> ContractDocument:
    """Build a minimal Class A ContractDocument for testing."""
    if fields is None:
        fields = {
            "f1": FieldSpec(
                type="string",
                nullable=False,
                description="A field",
                semantics="The meaning",
                populated_by="writer",
                dq_intent={"not_null": {"enforced": True}},
            )
        }
    return ContractDocument(
        contract=ContractMeta(
            id=contract_id,
            **{"class": ContractClass.A},
            contract_version=1,
            status=status,
            description=description,
        ),
        fields=fields,
        amendment_log=amendment_log,
    )


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


class TestParseCondition:
    def test_valid_production_invocations(self) -> None:
        result = _parse_condition("production_invocations >= 100")
        assert result == ("production_invocations", 100)

    def test_valid_days_elapsed(self) -> None:
        result = _parse_condition("days_since_first_production_invocation >= 30")
        assert result == ("days_since_first_production_invocation", 30)

    def test_no_operator_returns_none(self) -> None:
        assert _parse_condition("production_invocations = 5") is None

    def test_unknown_lhs_returns_none(self) -> None:
        assert _parse_condition("unknown_metric >= 10") is None

    def test_non_integer_rhs_returns_none(self) -> None:
        assert _parse_condition("production_invocations >= abc") is None

    def test_empty_string_returns_none(self) -> None:
        assert _parse_condition("") is None

    def test_whitespace_trimmed(self) -> None:
        result = _parse_condition("  production_invocations  >=  50  ")
        assert result == ("production_invocations", 50)


class TestEvaluateProvisionalTrigger:
    def _make_provisional_doc(
        self,
        first_of: list[str],
        *,
        contract_id: str = "prov-test",
    ) -> ContractDocument:
        from scripts.contracts_schema import ContractMeta  # noqa: PLC0415

        return ContractDocument(
            contract=ContractMeta(
                id=contract_id,
                **{"class": ContractClass.A},
                contract_version=1,
                status=ContractStatus.provisional_v0,
                provisional_v0={
                    "declared_at": "2026-01-01",
                    "re_ratification_trigger": {"first_of": first_of},
                },
            ),
            fields={
                "f1": FieldSpec(
                    type="string",
                    nullable=False,
                    description="A field",
                    semantics="The meaning",
                    populated_by="writer",
                    dq_intent={"not_null": {"enforced": True}},
                )
            },
        )

    def test_non_provisional_returns_false(self) -> None:
        doc = _make_class_a_doc(status=ContractStatus.draft)
        met, cond = evaluate_provisional_trigger(doc, {"production_invocations": 999})
        assert met is False
        assert cond is None

    def test_no_provisional_v0_block_returns_false(self) -> None:
        doc = ContractDocument(
            contract=ContractMeta(
                id="prov-no-block",
                **{"class": ContractClass.A},
                contract_version=1,
                status=ContractStatus.provisional_v0,
                provisional_v0=None,
            ),
            fields={"f1": FieldSpec(type="string", nullable=False)},
        )
        met, cond = evaluate_provisional_trigger(doc, {"production_invocations": 999})
        assert met is False

    def test_no_trigger_in_provisional_block_returns_false(self) -> None:
        doc = ContractDocument(
            contract=ContractMeta(
                id="prov-no-trigger",
                **{"class": ContractClass.A},
                contract_version=1,
                status=ContractStatus.provisional_v0,
                provisional_v0={"declared_at": "2026-01-01"},
            ),
            fields={"f1": FieldSpec(type="string", nullable=False)},
        )
        met, cond = evaluate_provisional_trigger(doc, {})
        assert met is False

    def test_no_first_of_returns_false(self) -> None:
        doc = ContractDocument(
            contract=ContractMeta(
                id="prov-no-firstof",
                **{"class": ContractClass.A},
                contract_version=1,
                status=ContractStatus.provisional_v0,
                provisional_v0={"re_ratification_trigger": {}},
            ),
            fields={"f1": FieldSpec(type="string", nullable=False)},
        )
        met, cond = evaluate_provisional_trigger(doc, {})
        assert met is False

    def test_met_production_invocations(self) -> None:
        doc = self._make_provisional_doc(["production_invocations >= 10"])
        met, cond = evaluate_provisional_trigger(doc, {"production_invocations": 15})
        assert met is True
        assert cond == "production_invocations >= 10"

    def test_unmet_production_invocations(self) -> None:
        doc = self._make_provisional_doc(["production_invocations >= 10"])
        met, cond = evaluate_provisional_trigger(doc, {"production_invocations": 5})
        assert met is False
        assert cond is None

    def test_met_days_elapsed(self) -> None:
        doc = self._make_provisional_doc(["days_since_first_production_invocation >= 30"])
        met, cond = evaluate_provisional_trigger(doc, {"days_since_first_production_invocation": 30})
        assert met is True
        assert "days_since" in cond  # type: ignore[operator]

    def test_first_of_semantics_fires_first_met(self) -> None:
        doc = self._make_provisional_doc(
            [
                "production_invocations >= 100",  # not met
                "days_since_first_production_invocation >= 30",  # met
            ]
        )
        metrics = {"production_invocations": 50, "days_since_first_production_invocation": 45}
        met, cond = evaluate_provisional_trigger(doc, metrics)
        assert met is True
        assert "days_since_first" in cond  # type: ignore[operator]

    def test_none_metrics_returns_false(self) -> None:
        doc = self._make_provisional_doc(["production_invocations >= 1"])
        met, cond = evaluate_provisional_trigger(doc, None)
        assert met is False

    def test_absent_metric_returns_false(self) -> None:
        doc = self._make_provisional_doc(["production_invocations >= 1"])
        met, cond = evaluate_provisional_trigger(doc, {"days_since_first_production_invocation": 999})
        assert met is False

    def test_non_string_condition_skipped(self) -> None:
        doc = ContractDocument(
            contract=ContractMeta(
                id="prov-badcond",
                **{"class": ContractClass.A},
                contract_version=1,
                status=ContractStatus.provisional_v0,
                provisional_v0={"re_ratification_trigger": {"first_of": [42, None]}},
            ),
            fields={"f1": FieldSpec(type="string", nullable=False)},
        )
        met, cond = evaluate_provisional_trigger(doc, {"production_invocations": 999})
        assert met is False

    def test_unparseable_condition_skipped(self) -> None:
        doc = self._make_provisional_doc(["garbage_metric >= 10"])
        met, cond = evaluate_provisional_trigger(doc, {"garbage_metric": 999})
        assert met is False

    def test_non_integer_metric_value_skipped(self) -> None:
        doc = self._make_provisional_doc(["production_invocations >= 10"])
        met, cond = evaluate_provisional_trigger(doc, {"production_invocations": "not_a_number"})
        assert met is False
