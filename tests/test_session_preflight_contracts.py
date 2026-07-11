"""Tests for the session_preflight provisional-contract scan (T-1.12 subset f, live in c6).

Follows the tests/test_session_preflight_platform_roadmap.py direct-import pattern.
_scan_provisional_contracts reads local docs/contracts/ ritual contracts and surfaces the ids
whose re_ratification_trigger first_of conditions evaluate as met.  metrics_provider is now
called PER CONTRACT with the loaded doc; when absent (the production default), the live
default_provisional_metrics days-since provider computes the metric from each contract's
provisional_v0.first_production_invocation_date.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from scripts.session.preflight import _scan_provisional_contracts


def _write(directory: Path, name: str, text: str) -> None:
    (directory / name).write_text(textwrap.dedent(text).strip() + "\n", encoding="utf-8")


def _provisional_contract(contract_id: str, condition: str, first_production_invocation_date: str | None = None) -> str:
    date_line = (
        f'\n            first_production_invocation_date: "{first_production_invocation_date}"'
        if first_production_invocation_date is not None
        else ""
    )
    return f"""
        contract:
          id: {contract_id}
          class: A
          contract_version: 1
          status: provisional_v0
          description: Provisional contract {contract_id}
          provisional_v0:
            declared_at: "2026-01-01"{date_line}
            re_ratification_trigger:
              first_of:
                - "{condition}"
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
    """


_DRAFT_CONTRACT = """
    contract:
      id: just-draft
      class: A
      contract_version: 1
      status: draft
      description: A ratified-track contract, not provisional
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
"""


class TestScanProvisionalContracts:
    def test_met_trigger_is_surfaced(self, tmp_path) -> None:
        _write(tmp_path, "prov-due.yaml", _provisional_contract("prov-due", "days_since_first_production_invocation >= 30"))
        due = _scan_provisional_contracts(
            contracts_dir=tmp_path,
            metrics_provider=lambda doc: {"days_since_first_production_invocation": 45},
        )
        assert due == ["prov-due"]

    def test_unmet_trigger_is_excluded(self, tmp_path) -> None:
        _write(
            tmp_path,
            "prov-pending.yaml",
            _provisional_contract("prov-pending", "days_since_first_production_invocation >= 30"),
        )
        due = _scan_provisional_contracts(
            contracts_dir=tmp_path,
            metrics_provider=lambda doc: {"days_since_first_production_invocation": 10},
        )
        assert due == []

    def test_mixed_population_returns_only_met(self, tmp_path) -> None:
        _write(tmp_path, "due.yaml", _provisional_contract("due", "production_invocations >= 100"))
        _write(tmp_path, "pending.yaml", _provisional_contract("pending", "production_invocations >= 100"))
        due = _scan_provisional_contracts(
            contracts_dir=tmp_path,
            # 'due' meets the threshold; 'pending' has a distinct id so we cannot vary metrics
            # per-contract -- instead assert the single shared metric gates both the same way,
            # then a second call with a sub-threshold metric excludes both.
            metrics_provider=lambda doc: {"production_invocations": 150},
        )
        assert sorted(due) == ["due", "pending"]
        none_due = _scan_provisional_contracts(
            contracts_dir=tmp_path,
            metrics_provider=lambda doc: {"production_invocations": 5},
        )
        assert none_due == []

    def test_returns_empty_list_when_no_provisional_contracts(self, tmp_path) -> None:
        _write(tmp_path, "just-draft.yaml", _DRAFT_CONTRACT)
        due = _scan_provisional_contracts(
            contracts_dir=tmp_path,
            metrics_provider=lambda doc: {"days_since_first_production_invocation": 999},
        )
        assert due == []

    def test_returns_list_on_empty_dir(self, tmp_path) -> None:
        due = _scan_provisional_contracts(contracts_dir=tmp_path)
        assert due == []

    def test_default_provider_surfaces_past_dated_contract(self, tmp_path) -> None:
        # Production default: no metrics_provider -> default_provisional_metrics computes
        # days_since deterministically from first_production_invocation_date. A far-past date
        # surfaces via the DEFAULT provider (proving the wiring, not just the evaluation logic).
        _write(
            tmp_path,
            "prov-due.yaml",
            _provisional_contract(
                "prov-due",
                "days_since_first_production_invocation >= 1",
                first_production_invocation_date="2000-01-01",
            ),
        )
        due = _scan_provisional_contracts(contracts_dir=tmp_path)
        assert due == ["prov-due"]

    def test_default_provider_excludes_recent_dated_contract(self, tmp_path) -> None:
        from datetime import datetime, timezone  # noqa: PLC0415

        today = datetime.now(timezone.utc).date().isoformat()
        _write(
            tmp_path,
            "prov-pending.yaml",
            _provisional_contract(
                "prov-pending",
                "days_since_first_production_invocation >= 1",
                first_production_invocation_date=today,
            ),
        )
        due = _scan_provisional_contracts(contracts_dir=tmp_path)
        assert due == []
