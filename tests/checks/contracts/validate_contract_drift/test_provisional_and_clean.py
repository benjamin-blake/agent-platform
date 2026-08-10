"""re_ratification_trigger well-formedness (Pass 1, provisional-contract-alarm plan) and the
clean / no-op cases, migrated verbatim in spirit from the pre-decomposition
tests/checks/contracts/test_validate_contract_drift.py monolith (T2.56 concern-split)."""

from __future__ import annotations

import textwrap
from pathlib import Path

from .conftest import validate_contract_drift

_REAL_CONTRACTS_DIR = Path(__file__).resolve().parents[4] / "docs" / "contracts"


class TestReRatificationTriggerWellFormedness:
    def test_malformed_trigger_condition_rejected(self, tmp_path, install_fake_git, write_contract, FakeGit) -> None:
        install_fake_git(FakeGit(merge_base_rc=1))
        text = textwrap.dedent(
            """
            contract:
              id: provbad
              class: A
              contract_version: 1
              status: provisional_v0
              description: Provisional bad trigger
              provisional_v0:
                declared_at: "2026-01-01"
                first_production_invocation_date: "2026-06-08"
                re_ratification_trigger:
                  first_of:
                    - "not a valid condition"
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
        ).strip()
        write_contract(tmp_path, "provbad.yaml", text + "\n")
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("provbad.yaml" in f and "unparseable" in f for f in failed)

    def test_missing_date_for_days_since_condition_rejected(self, tmp_path, install_fake_git, write_contract, FakeGit) -> None:
        install_fake_git(FakeGit(merge_base_rc=1))
        text = textwrap.dedent(
            """
            contract:
              id: provnodate
              class: A
              contract_version: 1
              status: provisional_v0
              description: Provisional missing date
              provisional_v0:
                declared_at: "2026-01-01"
                re_ratification_trigger:
                  first_of:
                    - "days_since_first_production_invocation >= 60"
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
        ).strip()
        write_contract(tmp_path, "provnodate.yaml", text + "\n")
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert any("provnodate.yaml" in f and "first_production_invocation_date" in f for f in failed)

    def test_valid_provisional_contract_passes(self, tmp_path, install_fake_git, write_contract, FakeGit) -> None:
        install_fake_git(FakeGit(merge_base_rc=1))
        text = textwrap.dedent(
            """
            contract:
              id: provgood
              class: A
              contract_version: 1
              status: provisional_v0
              description: Provisional good trigger
              provisional_v0:
                declared_at: "2026-01-01"
                first_production_invocation_date: "2026-06-08"
                re_ratification_trigger:
                  first_of:
                    - "production_invocations >= 500"
                    - "days_since_first_production_invocation >= 60"
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
        ).strip()
        write_contract(tmp_path, "provgood.yaml", text + "\n")
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert failed == []

    def test_real_live_contracts_pass(self, install_fake_git, FakeGit) -> None:
        install_fake_git(FakeGit(merge_base_rc=1))
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=_REAL_CONTRACTS_DIR)
        assert failed == []


class TestCleanAndNoRitual:
    def test_well_formed_contract_passes_pass1(
        self, tmp_path, install_fake_git, write_contract, FakeGit, valid_class_a
    ) -> None:
        install_fake_git(FakeGit(merge_base_rc=1))
        write_contract(tmp_path, "alpha.yaml", valid_class_a())
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert failed == []

    def test_changed_contract_with_no_drift_passes_pass2(
        self, tmp_path, install_fake_git, write_contract, FakeGit, valid_class_a
    ) -> None:
        same = valid_class_a(contract_id="alpha")
        write_contract(tmp_path, "alpha.yaml", same)
        install_fake_git(
            FakeGit(merge_base_rc=0, changed=["docs/contracts/alpha.yaml"], show_map={"docs/contracts/alpha.yaml": same})
        )
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert failed == []

    def test_non_ritual_only_dir_passes(self, tmp_path, install_fake_git, write_contract, FakeGit) -> None:
        install_fake_git(FakeGit(merge_base_rc=1))
        write_contract(tmp_path, "read-engine.yaml", "version: 3\nengine: duckdb\n")
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path)
        assert failed == []

    def test_missing_contracts_dir_is_skipped(self, tmp_path, install_fake_git, FakeGit) -> None:
        install_fake_git(FakeGit(merge_base_rc=1))
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=tmp_path / "does_not_exist")
        # Now FAIL-CLOSED (h): a missing docs/contracts directory FAILS rather than silently
        # skipping. This is a deliberate behavior change from the pre-migration gate -- see
        # TestFailClosed::test_missing_docs_contracts_directory_fails for the dedicated coverage.
        assert failed != []
