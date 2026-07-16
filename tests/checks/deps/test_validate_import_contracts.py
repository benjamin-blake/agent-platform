"""Tests for validate_import_contracts() -- thin wrapper around import_governance.run_import_contracts."""

from unittest.mock import patch

from scripts.checks.deps.validate_import_contracts import validate_import_contracts


class TestValidateImportContracts:
    """Tests for validate_import_contracts() -- thin wrapper around import_governance.run_import_contracts."""

    def test_passes_on_clean_tree(self) -> None:
        """Contracts pass on the unmodified repository tree (integration smoke)."""
        failed: list[str] = []
        validate_import_contracts(failed)
        assert not failed, f"Unexpected import-contract failures: {failed}"

    def test_appends_to_failed_on_contract_breach(self) -> None:
        """When run_import_contracts returns (False, ...), failure is appended."""
        from scripts import import_governance  # noqa: PLC0415

        failed: list[str] = []
        with patch.object(import_governance, "run_import_contracts", return_value=(False, "BROKEN: bad cycle\n")):
            validate_import_contracts(failed)
        assert any("Import contracts" in f for f in failed)

    def test_no_failure_on_pass(self) -> None:
        """When run_import_contracts returns (True, ...), nothing is appended to failed."""
        from scripts import import_governance  # noqa: PLC0415

        failed: list[str] = []
        with patch.object(import_governance, "run_import_contracts", return_value=(True, "All contracts kept\n")):
            validate_import_contracts(failed)
        assert not failed

    def test_wired_in_both_tiers(self) -> None:
        """validate_import_contracts is a registered check in both the --pre and full-tier sequences.

        Decision 104: dispatch is registry-driven (scripts/checks/registry.py), not a literal
        `validate_import_contracts(failed)` call site in scripts/validate.py -- so tier membership
        is verified via the registry's declared sequences, not AST call-site counting.
        """
        from scripts.checks import registry  # noqa: PLC0415

        pre_names = {step.name for step in registry.pre_sequence() if step.kind == "check"}
        full_names = {step.name for step in registry.full_sequence() if step.kind == "check"}
        assert "validate_import_contracts" in pre_names, "validate_import_contracts missing from pre_sequence()"
        assert "validate_import_contracts" in full_names, "validate_import_contracts missing from full_sequence()"
