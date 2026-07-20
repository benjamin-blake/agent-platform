"""Tests for validate_data_model_standard() -- PLAN-scd2-modeling-defaults.

Covers: a merge_key-bearing storage-substrate entry missing grain fails, a complete entry
passes, a group entry without merge_key is skipped (no false positive), a missing/malformed
data-modeling-standard.yaml fails, the diff gate skips when neither trigger file changed, and
the check is wired into both presubmit tiers + the scripts.validate facade (VP step 2, -k
wiring). Follows the tmp_path + contracts_dir/changed_files override pattern used by
test_validate_intent_doc_freeze.py / test_validate_contract_drift.py.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import yaml

from scripts.checks import registry
from scripts.checks.contracts.validate_data_model_standard import validate_data_model_standard

_COMPLETE_STANDARD = {
    "version": 1,
    "rules": [{"id": "grain-first", "statement": "name the grain first"}],
    "write_modes": {"scd2": {}, "append_only": {}},
    "indexes": [{"target": "docs/contracts/storage-substrate.yaml"}],
}


def _write_yaml(path: Path, data: object) -> None:
    path.write_text(yaml.dump(data), encoding="utf-8")


class TestStorageSubstrateGate:
    def test_merge_key_entry_missing_grain_fails(self, tmp_path: Path) -> None:
        substrate = {"tables": {"ops_priority_queue": {"merge_key": "rec_id", "write_mode": "scd2"}}}
        _write_yaml(tmp_path / "storage-substrate.yaml", substrate)

        failed: list[str] = []
        validate_data_model_standard(failed, contracts_dir=tmp_path, changed_files=["docs/contracts/storage-substrate.yaml"])

        assert any("ops_priority_queue" in f for f in failed)

    def test_complete_entry_passes(self, tmp_path: Path) -> None:
        substrate = {
            "tables": {"ops_priority_queue": {"merge_key": "rec_id", "grain": "one row per rec_id", "write_mode": "scd2"}}
        }
        _write_yaml(tmp_path / "storage-substrate.yaml", substrate)

        failed: list[str] = []
        validate_data_model_standard(failed, contracts_dir=tmp_path, changed_files=["docs/contracts/storage-substrate.yaml"])

        assert failed == []

    def test_group_entry_without_merge_key_skipped(self, tmp_path: Path) -> None:
        substrate = {"tables": {"telemetry_tables": {"note": "group entry, no merge_key"}}}
        _write_yaml(tmp_path / "storage-substrate.yaml", substrate)

        failed: list[str] = []
        validate_data_model_standard(failed, contracts_dir=tmp_path, changed_files=["docs/contracts/storage-substrate.yaml"])

        assert failed == []

    def test_missing_tables_mapping_fails(self, tmp_path: Path) -> None:
        _write_yaml(tmp_path / "storage-substrate.yaml", {"version": 1})

        failed: list[str] = []
        validate_data_model_standard(failed, contracts_dir=tmp_path, changed_files=["docs/contracts/storage-substrate.yaml"])

        assert any("tables" in f for f in failed)

    def test_read_error_reported(self, tmp_path: Path, monkeypatch) -> None:
        path = tmp_path / "storage-substrate.yaml"
        path.write_text("tables: {}", encoding="utf-8")

        def _raise(self: Path, *args: object, **kwargs: object) -> str:
            raise OSError("permission denied")

        monkeypatch.setattr(Path, "read_text", _raise)

        failed: list[str] = []
        validate_data_model_standard(failed, contracts_dir=tmp_path, changed_files=["docs/contracts/storage-substrate.yaml"])

        assert any("could not read" in f for f in failed)


class TestStandardContractGate:
    def test_missing_file_fails(self, tmp_path: Path) -> None:
        failed: list[str] = []
        validate_data_model_standard(
            failed, contracts_dir=tmp_path, changed_files=["docs/contracts/data-modeling-standard.yaml"]
        )

        assert any("not found" in f for f in failed)

    def test_non_mapping_standard_fails(self, tmp_path: Path) -> None:
        (tmp_path / "data-modeling-standard.yaml").write_text("- a\n- b\n", encoding="utf-8")

        failed: list[str] = []
        validate_data_model_standard(
            failed, contracts_dir=tmp_path, changed_files=["docs/contracts/data-modeling-standard.yaml"]
        )

        assert any("not a YAML mapping" in f for f in failed)

    def test_contract_bearing_key_fails(self, tmp_path: Path) -> None:
        data = dict(_COMPLETE_STANDARD)
        data["contract"] = {"class": "A"}
        _write_yaml(tmp_path / "data-modeling-standard.yaml", data)

        failed: list[str] = []
        validate_data_model_standard(
            failed, contracts_dir=tmp_path, changed_files=["docs/contracts/data-modeling-standard.yaml"]
        )

        assert any("contract:/class:" in f for f in failed)

    def test_missing_section_fails(self, tmp_path: Path) -> None:
        _write_yaml(tmp_path / "data-modeling-standard.yaml", {"version": 1, "rules": []})

        failed: list[str] = []
        validate_data_model_standard(
            failed, contracts_dir=tmp_path, changed_files=["docs/contracts/data-modeling-standard.yaml"]
        )

        assert any("missing required section" in f for f in failed)

    def test_malformed_yaml_fails(self, tmp_path: Path) -> None:
        (tmp_path / "data-modeling-standard.yaml").write_text("rules: [unterminated", encoding="utf-8")

        failed: list[str] = []
        validate_data_model_standard(
            failed, contracts_dir=tmp_path, changed_files=["docs/contracts/data-modeling-standard.yaml"]
        )

        assert any("could not parse" in f for f in failed)

    def test_complete_standard_passes(self, tmp_path: Path) -> None:
        _write_yaml(tmp_path / "data-modeling-standard.yaml", _COMPLETE_STANDARD)

        failed: list[str] = []
        validate_data_model_standard(
            failed, contracts_dir=tmp_path, changed_files=["docs/contracts/data-modeling-standard.yaml"]
        )

        assert failed == []


class TestDiffGate:
    def test_neither_file_changed_skips(self, tmp_path: Path) -> None:
        failed: list[str] = []
        validate_data_model_standard(failed, contracts_dir=tmp_path, changed_files=[])

        assert failed == []

    def test_both_files_changed_runs_both_checks(self, tmp_path: Path) -> None:
        _write_yaml(
            tmp_path / "storage-substrate.yaml",
            {"tables": {"ops_priority_queue": {"merge_key": "rec_id"}}},
        )
        _write_yaml(tmp_path / "data-modeling-standard.yaml", _COMPLETE_STANDARD)

        failed: list[str] = []
        validate_data_model_standard(
            failed,
            contracts_dir=tmp_path,
            changed_files=[
                "docs/contracts/storage-substrate.yaml",
                "docs/contracts/data-modeling-standard.yaml",
            ],
        )

        assert any("ops_priority_queue" in f for f in failed)
        assert len(failed) == 1


class TestWiring:
    def test_wiring_registered_in_both_sequences(self) -> None:
        pre_names = {step.name for step in registry.pre_sequence() if step.kind == "check"}
        full_names = {step.name for step in registry.full_sequence() if step.kind == "check"}

        assert "validate_data_model_standard" in pre_names
        assert "validate_data_model_standard" in full_names

    def test_wiring_resolves_on_validate_facade(self) -> None:
        mod = importlib.import_module("scripts.validate")

        assert hasattr(mod, "validate_data_model_standard")
        assert callable(mod.validate_data_model_standard)
