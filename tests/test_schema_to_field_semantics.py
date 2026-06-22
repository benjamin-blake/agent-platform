"""Unit tests for scripts/schema_to_field_semantics.py (T2.33).

Hermetic: uses tmp_path fixtures for any file I/O; no network calls; no database.
Covers:
  - iceberg->sql type mapping (all mapped types + unmapped raises)
  - role rule: realized:true -> derived, realized:false -> input, no derivation -> input
  - SCD2 envelope fields (ulid/created/last_updated are derived)
  - effort/priority/risk/automatable remain input (realized:false)
  - merge_key and partition synthesis
  - history/current table name synthesis
  - mechanical slice has no prose (no description/semantics)
  - semantic slice carries description/semantics
  - full-document data-equivalence vs the pre-change committed file (keystone safety gate)
  - --check detects injected drift without writing
  - migration_columns subset enforcement raises on non-subset/mistyped entry (rec-2232)
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml

# ---------------------------------------------------------------------------
# Module import (direct load to avoid sys.path pollution)
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).parent.parent
_MODULE_PATH = _ROOT / "scripts" / "schema_to_field_semantics.py"
_spec = importlib.util.spec_from_file_location("schema_to_field_semantics", _MODULE_PATH)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

_map_iceberg_type = _mod._map_iceberg_type
_project_role = _mod._project_role
_enforce_migration_columns_subset = _mod._enforce_migration_columns_subset
_project_contract_table = _mod._project_contract_table
_emit_yaml = _mod._emit_yaml
generate = _mod.generate
generate_mechanical_slice = _mod.generate_mechanical_slice
generate_semantic_slice = _mod.generate_semantic_slice
main = _mod.main


# ---------------------------------------------------------------------------
# Iceberg -> sql_type mapping
# ---------------------------------------------------------------------------
class TestIcebergToSqlMapping:
    def test_string_maps_to_varchar(self) -> None:
        assert _map_iceberg_type("string", "f") == "VARCHAR"

    def test_boolean_maps(self) -> None:
        assert _map_iceberg_type("boolean", "f") == "BOOLEAN"

    def test_long_maps_to_bigint(self) -> None:
        assert _map_iceberg_type("long", "f") == "BIGINT"

    def test_int_maps_to_integer(self) -> None:
        assert _map_iceberg_type("int", "f") == "INTEGER"

    def test_timestamptz_maps(self) -> None:
        assert _map_iceberg_type("timestamptz", "f") == "TIMESTAMP WITH TIME ZONE"

    def test_array_string_maps(self) -> None:
        assert _map_iceberg_type("array<string>", "f") == "VARCHAR[]"

    def test_array_long_maps(self) -> None:
        assert _map_iceberg_type("array<long>", "f") == "BIGINT[]"

    def test_unmapped_raises(self) -> None:
        with pytest.raises(ValueError, match="no sql_type mapping"):
            _map_iceberg_type("uuid", "bad_field")

    def test_none_iceberg_type_raises(self) -> None:
        with pytest.raises(ValueError, match="iceberg_type is None"):
            _map_iceberg_type(None, "bad_field")


# ---------------------------------------------------------------------------
# Role derivation rule
# ---------------------------------------------------------------------------
class TestProjectRole:
    def test_no_derivation_is_input(self) -> None:
        assert _project_role(None) == "input"

    def test_empty_derivation_is_input(self) -> None:
        assert _project_role({}) == "input"

    def test_realized_true_is_derived(self) -> None:
        assert _project_role({"realized": True}) == "derived"

    def test_realized_false_is_input(self) -> None:
        assert _project_role({"realized": False}) == "input"

    def test_realized_missing_is_input(self) -> None:
        assert _project_role({"formula": "some formula"}) == "input"

    def test_derived_requires_exact_true(self) -> None:
        assert _project_role({"realized": 1}) == "input"  # 1 != True (strict check)
        assert _project_role({"realized": "true"}) == "input"  # string "true" is not True


# ---------------------------------------------------------------------------
# Migration columns subset enforcement
# ---------------------------------------------------------------------------
class TestMigrationColumnsSubset:
    def _projected(self) -> dict[str, Any]:
        return {
            "id": {"role": "input", "sql_type": "VARCHAR", "nullable": False},
            "title": {"role": "input", "sql_type": "VARCHAR", "nullable": True},
        }

    def test_valid_subset_passes(self) -> None:
        _enforce_migration_columns_subset(
            "t",
            {"history": {"title": {"role": "input", "sql_type": "VARCHAR", "nullable": True}}},
            self._projected(),
        )

    def test_unknown_column_raises(self) -> None:
        with pytest.raises(ValueError, match="not in the projected columns"):
            _enforce_migration_columns_subset(
                "t",
                {"history": {"__bogus__": {"role": "input", "sql_type": "VARCHAR", "nullable": True}}},
                self._projected(),
            )

    def test_sql_type_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="sql_type mismatch"):
            _enforce_migration_columns_subset(
                "t",
                {"history": {"id": {"role": "input", "sql_type": "BIGINT", "nullable": False}}},
                self._projected(),
            )

    def test_both_history_and_current_checked(self) -> None:
        # current entry is valid, history entry is not -- should still raise
        with pytest.raises(ValueError, match="not in the projected columns"):
            _enforce_migration_columns_subset(
                "t",
                {
                    "history": {"__bad__": {"role": "input", "sql_type": "VARCHAR", "nullable": True}},
                    "current": {"title": {"role": "input", "sql_type": "VARCHAR", "nullable": True}},
                },
                self._projected(),
            )

    def test_non_dict_location_entry_is_skipped(self) -> None:
        # If the value under "history" or "current" is not a dict, continue (line 92)
        _enforce_migration_columns_subset(
            "t",
            {"history": ["not", "a", "dict"]},
            self._projected(),
        )

    def test_non_dict_col_spec_is_skipped(self) -> None:
        # If col_spec is not a dict, skip type-consistency check (line 100)
        _enforce_migration_columns_subset(
            "t",
            {"history": {"id": None}},
            self._projected(),
        )


# ---------------------------------------------------------------------------
# Integration: generate() against the real contracts + sidecar
# ---------------------------------------------------------------------------
class TestGenerateIntegration:
    """These tests call generate() which reads real files from the repo."""

    def test_ops_recommendations_columns_present(self) -> None:
        doc = generate()
        cols = doc["ops_tables"]["ops_recommendations"]["columns"]
        assert "ulid" in cols
        assert "id" in cols
        assert "_contract_version" in cols
        assert len(cols) == 26

    def test_ops_decisions_columns_present(self) -> None:
        doc = generate()
        cols = doc["ops_tables"]["ops_decisions"]["columns"]
        assert "ulid" in cols
        assert "id" in cols
        assert "_contract_version" in cols
        assert len(cols) == 14

    def test_envelope_fields_are_derived(self) -> None:
        doc = generate()
        for tbl in ("ops_recommendations", "ops_decisions"):
            cols = doc["ops_tables"][tbl]["columns"]
            assert cols["ulid"]["role"] == "derived", f"{tbl}.ulid should be derived"
            assert cols["created_timestamp"]["role"] == "derived", f"{tbl}.created_timestamp should be derived"
            assert cols["last_updated_timestamp"]["role"] == "derived", f"{tbl}.last_updated_timestamp should be derived"

    def test_deferred_derivation_fields_are_input(self) -> None:
        doc = generate()
        cols = doc["ops_tables"]["ops_recommendations"]["columns"]
        for fname in ("effort", "priority", "automatable", "risk"):
            assert cols[fname]["role"] == "input", f"{fname} should be input (realized:false)"

    def test_merge_key_projected(self) -> None:
        doc = generate()
        assert doc["ops_tables"]["ops_recommendations"]["merge_key"] == "id"
        assert doc["ops_tables"]["ops_decisions"]["merge_key"] == "id"

    def test_partition_synthesized(self) -> None:
        doc = generate()
        rec_part = doc["ops_tables"]["ops_recommendations"]["partition"]
        assert rec_part["history"] == "day(created_timestamp)"
        assert rec_part["current"] == "bucket(8, id)"

    def test_table_names_synthesized(self) -> None:
        doc = generate()
        rec = doc["ops_tables"]["ops_recommendations"]
        assert rec["history_table"] == "ops_recommendations_history"
        assert rec["current_table"] == "ops_recommendations_current"
        dec = doc["ops_tables"]["ops_decisions"]
        assert dec["history_table"] == "ops_decisions_history"
        assert dec["current_table"] == "ops_decisions_current"

    def test_dormant_tables_present(self) -> None:
        doc = generate()
        for tbl in ("ops_priority_queue", "ops_session_log", "ops_execution_plans"):
            assert tbl in doc["ops_tables"], f"{tbl} should be in ops_tables"
            assert doc["ops_tables"][tbl]["status"] == "dormant"

    def test_smoke_section_present(self) -> None:
        doc = generate()
        for key in ("tables", "fields", "derivation_timing", "partition_transforms", "connection_settings"):
            assert key in doc, f"smoke section key {key!r} missing"

    def test_mechanical_slice_has_no_prose(self) -> None:
        doc = generate(include_prose=False)
        for tbl_entry in doc["ops_tables"].values():
            for col_spec in tbl_entry.get("columns", {}).values():
                assert "description" not in col_spec, "mechanical slice must not contain description"
                assert "semantics" not in col_spec, "mechanical slice must not contain semantics"

    def test_semantic_slice_has_prose(self) -> None:
        """--slice semantic output must contain description/semantics for non-dormant tables."""
        doc = generate(include_prose=True)
        rec_cols = doc["ops_tables"]["ops_recommendations"]["columns"]
        # id field has description and semantics in the contract
        assert "description" in rec_cols["id"] or "semantics" in rec_cols["id"], (
            "semantic slice should expose description or semantics for ops_recommendations.id"
        )

    def test_sql_types_from_mapping(self) -> None:
        doc = generate()
        cols = doc["ops_tables"]["ops_recommendations"]["columns"]
        assert cols["automatable"]["sql_type"] == "BOOLEAN"
        assert cols["execution_steps"]["sql_type"] == "BIGINT"
        assert cols["created_timestamp"]["sql_type"] == "TIMESTAMP WITH TIME ZONE"
        assert cols["dependencies"]["sql_type"] == "VARCHAR[]"

    def test_full_document_data_equivalence_vs_origin_main(self) -> None:
        """Keystone safety gate: regenerated data must equal pre-change file on origin/main."""
        import subprocess

        result = subprocess.run(
            ["git", "show", "origin/main:config/lambda/ducklake/field_semantics.yaml"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=_ROOT,
        )
        if result.returncode != 0:
            pytest.skip("origin/main not available; skipping data-equivalence gate")
        prior = yaml.safe_load(result.stdout)
        generated = yaml.safe_load(_emit_yaml(generate(include_prose=False)))
        assert prior == generated, (
            "Generated field_semantics.yaml data differs from origin/main -- "
            "the generator or sidecar changed semantics (role/sql_type/nullable/structure). "
            "VP step 3 FAIL: STOP and reconcile."
        )


# ---------------------------------------------------------------------------
# --check mode: detects drift without writing
# ---------------------------------------------------------------------------
class TestCheckMode:
    def test_check_passes_when_up_to_date(self, tmp_path: Path) -> None:
        generated = _emit_yaml(generate(include_prose=False))
        output = tmp_path / "field_semantics.yaml"
        output.write_text(generated, encoding="utf-8")

        with patch.object(_mod, "_OUTPUT_PATH", output):
            rc = main(["--check"])
        assert rc == 0

    def test_check_detects_drift_without_writing(self, tmp_path: Path) -> None:
        generated = _emit_yaml(generate(include_prose=False))
        drifted = generated + "\n# injected drift\n"
        output = tmp_path / "field_semantics.yaml"
        output.write_text(drifted, encoding="utf-8")

        with patch.object(_mod, "_OUTPUT_PATH", output):
            rc = main(["--check"])
        assert rc != 0
        # Verify the file was NOT auto-overwritten
        assert output.read_text(encoding="utf-8") == drifted, (
            "--check must not auto-write; file should still contain the injected drift"
        )

    def test_check_missing_file_fails(self, tmp_path: Path) -> None:
        output = tmp_path / "nonexistent.yaml"
        with patch.object(_mod, "_OUTPUT_PATH", output):
            rc = main(["--check"])
        assert rc != 0


# ---------------------------------------------------------------------------
# write mode
# ---------------------------------------------------------------------------
class TestWriteMode:
    def test_write_mode_writes_file(self, tmp_path: Path) -> None:
        output = tmp_path / "fs_out.yaml"
        with patch.object(_mod, "_OUTPUT_PATH", output):
            rc = main([])
        assert rc == 0
        assert output.exists()
        data = yaml.safe_load(output.read_text(encoding="utf-8"))
        assert "ops_tables" in data

    def test_write_mode_idempotent(self, tmp_path: Path) -> None:
        output = tmp_path / "fs_out.yaml"
        with patch.object(_mod, "_OUTPUT_PATH", output):
            main([])
            first_content = output.read_text(encoding="utf-8")
            main([])
            second_content = output.read_text(encoding="utf-8")
        assert first_content == second_content, "Generator must be byte-stable (idempotent)"


# ---------------------------------------------------------------------------
# Slice wrappers and main() --slice branches
# ---------------------------------------------------------------------------
class TestSlices:
    def test_generate_mechanical_slice_is_yaml_str(self) -> None:
        result = generate_mechanical_slice()
        assert isinstance(result, str)
        data = yaml.safe_load(result)
        assert "ops_tables" in data
        # mechanical slice is routed through _emit_yaml, so header is present
        assert "GENERATED" in result

    def test_generate_semantic_slice_returns_only_prose(self) -> None:
        result = generate_semantic_slice()
        assert isinstance(result, str)
        data = yaml.safe_load(result)
        assert "ops_tables" in data
        # Each column entry should only carry description/semantics (or be empty)
        for tbl_entry in data["ops_tables"].values():
            for col, spec in tbl_entry.get("columns", {}).items():
                assert set(spec.keys()) <= {"description", "semantics"}, (
                    f"{col} has unexpected keys in semantic slice: {set(spec.keys())}"
                )

    def test_main_slice_mechanical_stdout(self, capsys: pytest.CaptureFixture) -> None:
        rc = main(["--slice", "mechanical"])
        assert rc == 0
        out = capsys.readouterr().out
        data = yaml.safe_load(out)
        assert "ops_tables" in data

    def test_main_slice_semantic_stdout(self, capsys: pytest.CaptureFixture) -> None:
        rc = main(["--slice", "semantic"])
        assert rc == 0
        out = capsys.readouterr().out
        data = yaml.safe_load(out)
        assert "ops_tables" in data


# ---------------------------------------------------------------------------
# generate() error path: missing merge_key
# ---------------------------------------------------------------------------
class TestGenerateMissingMergeKey:
    def test_missing_merge_key_raises(self) -> None:
        from unittest.mock import MagicMock, patch

        mock_doc = MagicMock()
        mock_doc.governance = MagicMock()
        mock_doc.governance.merge_key = None

        with patch("scripts.contracts.load_contract", return_value=mock_doc):
            with pytest.raises(ValueError, match="governance.merge_key is missing"):
                generate()
