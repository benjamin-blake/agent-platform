"""Provisional-v0 re-ratification-trigger concern of scripts/contracts_enforcement.py (rec-2709 Wave 11).

Covers _parse_condition, evaluate_provisional_trigger, default_provisional_metrics, and
check_re_ratification_trigger. Split from tests/test_contracts_enforcement.py (VERBATIM move).
"""

from __future__ import annotations

from datetime import datetime, timezone

from scripts.contracts_enforcement import (
    _parse_condition,
    check_re_ratification_trigger,
    default_provisional_metrics,
    evaluate_provisional_trigger,
)
from scripts.contracts_schema import ContractClass, ContractDocument, ContractMeta, ContractStatus, FieldSpec
from tests.fixtures.contracts_enforcement import _make_class_a_doc


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


def _make_provisional_doc_with_date(
    *,
    first_of: list[str],
    first_production_invocation_date: str | None,
    status: ContractStatus = ContractStatus.provisional_v0,
) -> ContractDocument:
    provisional_v0: dict = {"re_ratification_trigger": {"first_of": first_of}}
    if first_production_invocation_date is not None:
        provisional_v0["first_production_invocation_date"] = first_production_invocation_date
    return ContractDocument(
        contract=ContractMeta(
            id="prov-metrics-test",
            **{"class": ContractClass.A},
            contract_version=1,
            status=status,
            provisional_v0=provisional_v0,
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


class TestDefaultProvisionalMetrics:
    def test_fired_via_past_date_and_injected_now(self) -> None:
        doc = _make_provisional_doc_with_date(
            first_of=["days_since_first_production_invocation >= 60"],
            first_production_invocation_date="2026-01-01",
        )
        now = datetime(2026, 6, 1, tzinfo=timezone.utc)
        metrics = default_provisional_metrics(doc, now=now)
        assert metrics == {"days_since_first_production_invocation": 151}
        met, cond = evaluate_provisional_trigger(doc, metrics)
        assert met is True
        assert cond == "days_since_first_production_invocation >= 60"

    def test_not_fired_via_recent_date(self) -> None:
        doc = _make_provisional_doc_with_date(
            first_of=["days_since_first_production_invocation >= 60"],
            first_production_invocation_date="2026-06-08",
        )
        now = datetime(2026, 6, 20, tzinfo=timezone.utc)
        metrics = default_provisional_metrics(doc, now=now)
        assert metrics == {"days_since_first_production_invocation": 12}
        met, cond = evaluate_provisional_trigger(doc, metrics)
        assert met is False

    def test_no_production_invocations_key_supplied(self) -> None:
        doc = _make_provisional_doc_with_date(
            first_of=["days_since_first_production_invocation >= 1"],
            first_production_invocation_date="2020-01-01",
        )
        metrics = default_provisional_metrics(doc, now=datetime(2026, 1, 1, tzinfo=timezone.utc))
        assert "production_invocations" not in metrics

    def test_absent_date_returns_empty_dict(self) -> None:
        doc = _make_provisional_doc_with_date(
            first_of=["days_since_first_production_invocation >= 1"],
            first_production_invocation_date=None,
        )
        assert default_provisional_metrics(doc) == {}

    def test_malformed_date_returns_empty_dict(self) -> None:
        doc = _make_provisional_doc_with_date(
            first_of=["days_since_first_production_invocation >= 1"],
            first_production_invocation_date="not-a-date",
        )
        assert default_provisional_metrics(doc) == {}

    def test_non_provisional_status_returns_empty_dict(self) -> None:
        doc = _make_provisional_doc_with_date(
            first_of=["days_since_first_production_invocation >= 1"],
            first_production_invocation_date="2020-01-01",
            status=ContractStatus.draft,
        )
        assert default_provisional_metrics(doc) == {}

    def test_missing_provisional_v0_block_returns_empty_dict(self) -> None:
        doc = ContractDocument(
            contract=ContractMeta(
                id="no-prov-block",
                **{"class": ContractClass.A},
                contract_version=1,
                status=ContractStatus.provisional_v0,
                provisional_v0=None,
            ),
            fields={"f1": FieldSpec(type="string", nullable=False)},
        )
        assert default_provisional_metrics(doc) == {}


class TestCheckReRatificationTrigger:
    def test_valid_trigger_passes(self) -> None:
        doc = _make_provisional_doc_with_date(
            first_of=["production_invocations >= 500", "days_since_first_production_invocation >= 60"],
            first_production_invocation_date="2026-06-08",
        )
        assert check_re_ratification_trigger(doc) == []

    def test_unparseable_condition_errors(self) -> None:
        doc = _make_provisional_doc_with_date(
            first_of=["not a valid condition"],
            first_production_invocation_date="2026-06-08",
        )
        errors = check_re_ratification_trigger(doc)
        assert any("unparseable" in e for e in errors)

    def test_days_since_without_date_errors(self) -> None:
        doc = _make_provisional_doc_with_date(
            first_of=["days_since_first_production_invocation >= 60"],
            first_production_invocation_date=None,
        )
        errors = check_re_ratification_trigger(doc)
        assert any("first_production_invocation_date" in e for e in errors)

    def test_malformed_date_errors(self) -> None:
        doc = _make_provisional_doc_with_date(
            first_of=["days_since_first_production_invocation >= 60"],
            first_production_invocation_date="not-a-date",
        )
        errors = check_re_ratification_trigger(doc)
        assert any("not a valid ISO date" in e for e in errors)

    def test_non_list_first_of_errors(self) -> None:
        doc = ContractDocument(
            contract=ContractMeta(
                id="bad-firstof",
                **{"class": ContractClass.A},
                contract_version=1,
                status=ContractStatus.provisional_v0,
                provisional_v0={"re_ratification_trigger": {"first_of": "not-a-list"}},
            ),
            fields={"f1": FieldSpec(type="string", nullable=False)},
        )
        errors = check_re_ratification_trigger(doc)
        assert any("non-empty list" in e for e in errors)

    def test_non_provisional_returns_empty(self) -> None:
        doc = _make_class_a_doc(status=ContractStatus.draft)
        assert check_re_ratification_trigger(doc) == []

    def test_missing_provisional_v0_block_returns_empty(self) -> None:
        doc = ContractDocument(
            contract=ContractMeta(
                id="no-prov-block-2",
                **{"class": ContractClass.A},
                contract_version=1,
                status=ContractStatus.provisional_v0,
                provisional_v0=None,
            ),
            fields={"f1": FieldSpec(type="string", nullable=False)},
        )
        assert check_re_ratification_trigger(doc) == []

    def test_missing_trigger_block_returns_empty(self) -> None:
        doc = ContractDocument(
            contract=ContractMeta(
                id="no-trigger-block",
                **{"class": ContractClass.A},
                contract_version=1,
                status=ContractStatus.provisional_v0,
                provisional_v0={"declared_at": "2026-01-01"},
            ),
            fields={"f1": FieldSpec(type="string", nullable=False)},
        )
        assert check_re_ratification_trigger(doc) == []

    def test_live_contracts_pass(self) -> None:
        from pathlib import Path  # noqa: PLC0415

        from scripts.contracts import load_contract  # noqa: PLC0415

        contracts_dir = Path(__file__).resolve().parents[2] / "docs" / "contracts"
        for name in ("ducklake_writer.yaml", "ducklake_reader.yaml", "ducklake_maintenance.yaml"):
            doc = load_contract(contracts_dir / name)
            assert check_re_ratification_trigger(doc) == [], f"{name} should have a well-formed trigger"
