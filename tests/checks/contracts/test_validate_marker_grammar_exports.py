"""Tests for validate_marker_grammar_exports() -- PLAN-class-d-contract-enforcers.

Covers: green path against a fixture matching the live _marker_guard.__all__, a drift red path,
an ABSENT/EMPTY-target red path, a missing-file red path, and a malformed-YAML red path.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from scripts.checks import _marker_guard, registry
from scripts.checks.contracts.validate_marker_grammar_exports import validate_marker_grammar_exports

_CONTRACT_NAME = "marker-grammar.yaml"


def _write_contract(contracts_dir: Path, exports: list[str]) -> None:
    doc = {"binding_surface": {"exports": exports}}
    (contracts_dir / _CONTRACT_NAME).write_text(yaml.dump(doc), encoding="utf-8")


class TestGreenPath:
    def test_matching_exports_passes(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, list(_marker_guard.__all__))

        failed: list[str] = []
        validate_marker_grammar_exports(failed, contracts_dir=tmp_path)

        assert failed == []


class TestDriftRedPath:
    def test_divergent_exports_fails(self, tmp_path: Path) -> None:
        declared = [*_marker_guard.__all__, "NotARealExport"]
        _write_contract(tmp_path, declared)

        failed: list[str] = []
        validate_marker_grammar_exports(failed, contracts_dir=tmp_path)

        assert any("declares exports=" in f for f in failed)

    def test_reordered_exports_fails(self, tmp_path: Path) -> None:
        declared = list(reversed(_marker_guard.__all__))
        _write_contract(tmp_path, declared)

        failed: list[str] = []
        validate_marker_grammar_exports(failed, contracts_dir=tmp_path)

        assert failed != []


class TestAbsentEmptyTarget:
    def test_missing_binding_surface_block_fails(self, tmp_path: Path) -> None:
        (tmp_path / _CONTRACT_NAME).write_text(yaml.dump({"version": 1}), encoding="utf-8")

        failed: list[str] = []
        validate_marker_grammar_exports(failed, contracts_dir=tmp_path)

        assert any("missing or empty" in f for f in failed)

    def test_empty_exports_list_fails(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, [])

        failed: list[str] = []
        validate_marker_grammar_exports(failed, contracts_dir=tmp_path)

        assert any("missing or empty" in f for f in failed)


class TestMissingFile:
    def test_missing_contract_file_fails(self, tmp_path: Path) -> None:
        failed: list[str] = []
        validate_marker_grammar_exports(failed, contracts_dir=tmp_path)

        assert any("not found" in f for f in failed)


class TestMalformedYaml:
    def test_malformed_yaml_fails(self, tmp_path: Path) -> None:
        (tmp_path / _CONTRACT_NAME).write_text("binding_surface: [unterminated", encoding="utf-8")

        failed: list[str] = []
        validate_marker_grammar_exports(failed, contracts_dir=tmp_path)

        assert any("could not read/parse" in f for f in failed)


class TestWiring:
    def test_wiring_registered_in_pre_and_full(self) -> None:
        pre_names = {step.name for step in registry.pre_sequence() if step.kind == "check"}
        full_names = {step.name for step in registry.full_sequence() if step.kind == "check"}

        assert "validate_marker_grammar_exports" in pre_names
        assert "validate_marker_grammar_exports" in full_names

    def test_wiring_resolves_via_registry(self) -> None:
        resolved = registry.resolve("validate_marker_grammar_exports")

        assert callable(resolved)
        assert resolved is validate_marker_grammar_exports
