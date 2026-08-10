"""VP step 9: regression and census against the REAL population with the baseline legs ENABLED
(real git, not the merge_base_rc=1 shortcut) -- so the census and ratchet are genuinely
exercised, and docs/contracts/contract-population.yaml passes the gate it defines."""

from __future__ import annotations

from pathlib import Path

from .conftest import validate_contract_drift

_REAL_CONTRACTS_DIR = Path(__file__).resolve().parents[4] / "docs" / "contracts"


class TestRealPopulationRegression:
    def test_real_population_passes_with_baseline_legs_enabled(self) -> None:
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=_REAL_CONTRACTS_DIR)
        assert failed == [], failed

    def test_real_population_census_counts_are_derived_and_nonzero(self, capsys) -> None:
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=_REAL_CONTRACTS_DIR)
        out = capsys.readouterr().out
        census_line = next(line for line in out.splitlines() if line.strip().startswith("Census:"))
        counts = dict(pair.split("=") for pair in census_line.strip().removeprefix("Census:").split())
        assert int(counts["scanned"]) > 0
        assert int(counts["ritual"]) > 0
        assert int(counts["skipped"]) == 0
        assert failed == []


class TestContractPopulationSelfHosting:
    def test_contract_population_yaml_passes_the_gate_it_defines(self) -> None:
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=_REAL_CONTRACTS_DIR)
        assert not any("contract-population.yaml" in f for f in failed), failed

    def test_contract_population_yaml_is_ratified_with_a_resolving_evaluator(self) -> None:
        from scripts.contracts import load_contract_meta

        meta = load_contract_meta(_REAL_CONTRACTS_DIR / "contract-population.yaml")
        assert meta.status.value == "ratified"
        assert meta.ratified_via
        assert meta.evaluator.check == "validate_contract_drift"
