"""Import-linter contract enforcement (Decision 104)."""

from __future__ import annotations

from scripts.checks import registry


@registry.register("validate_import_contracts", owner="platform")
def validate_import_contracts(failed: list[str]) -> None:
    """Thin wrapper: run import-linter contracts (Decision 80 / T3.11). Delegates to scripts.import_governance."""
    print("\n=== Import contracts (Decision 80 / T3.11) ===")
    from scripts import import_governance  # noqa: PLC0415

    passed, output = import_governance.run_import_contracts()
    print(output, end="")
    if not passed:
        failed.append("Import contracts (Decision 80)")
