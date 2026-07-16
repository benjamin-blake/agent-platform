"""Tests for validate_dq_manifest_gate() -- allowlist enforcement."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks.ops_governance.validate_dq_manifest_gate import validate_dq_manifest_gate


class TestValidateDqManifestGate:
    """Tests for validate_dq_manifest_gate() -- allowlist enforcement."""

    _OPS_YAML = (
        "tables:\n"
        "  ops_recommendations:\n"
        "    columns:\n"
        "      title:\n"
        "        tests:\n"
        "          - not_null:\n"
        "              enforced: true\n"
    )

    def _write_ops_yaml(self, tmp_path: Path, content: str = "") -> None:
        dq_dir = tmp_path / "config" / "agent" / "data_quality"
        dq_dir.mkdir(parents=True, exist_ok=True)
        (dq_dir / "ops.yaml").write_text(content or self._OPS_YAML, encoding="utf-8")

    def _write_manifest(self, tmp_path: Path, state: str) -> None:
        dec_dir = tmp_path / "config" / "agent" / "data_quality" / "decisions"
        dec_dir.mkdir(parents=True, exist_ok=True)
        manifest_yaml = f"table: ops_recommendations\nfields:\n  title:\n    enforcement_ready: {state}\n"
        (dec_dir / "ops_recommendations.yaml").write_text(manifest_yaml, encoding="utf-8")

    def _run(self, tmp_path: Path) -> list[str]:
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_dq_manifest_gate(failed)
        return failed

    def test_allowed_state_ready_now_passes(self, tmp_path: Path) -> None:
        self._write_ops_yaml(tmp_path)
        self._write_manifest(tmp_path, "READY_NOW")
        assert self._run(tmp_path) == []

    def test_allowed_state_write_fix_deployed_passes(self, tmp_path: Path) -> None:
        self._write_ops_yaml(tmp_path)
        self._write_manifest(tmp_path, "write_fix_deployed")
        assert self._run(tmp_path) == []

    def test_allowed_state_graduated_passes(self, tmp_path: Path) -> None:
        self._write_ops_yaml(tmp_path)
        self._write_manifest(tmp_path, "GRADUATED")
        assert self._run(tmp_path) == []

    def test_allowed_state_needs_temporal_gate_passes(self, tmp_path: Path) -> None:
        self._write_ops_yaml(tmp_path)
        self._write_manifest(tmp_path, "NEEDS_TEMPORAL_GATE")
        assert self._run(tmp_path) == []

    def test_blocked_state_needs_write_fix_fails(self, tmp_path: Path) -> None:
        self._write_ops_yaml(tmp_path)
        self._write_manifest(tmp_path, "NEEDS_WRITE_FIX")
        assert self._run(tmp_path) == ["DQ manifest gate"]

    def test_blocked_state_needs_data_correction_fails(self, tmp_path: Path) -> None:
        self._write_ops_yaml(tmp_path)
        self._write_manifest(tmp_path, "NEEDS_DATA_CORRECTION")
        assert self._run(tmp_path) == ["DQ manifest gate"]

    def test_unknown_state_fails_closed(self, tmp_path: Path) -> None:
        self._write_ops_yaml(tmp_path)
        self._write_manifest(tmp_path, "SOME_FUTURE_UNKNOWN_STATE")
        assert self._run(tmp_path) == ["DQ manifest gate"]

    def test_missing_manifest_entry_fails_closed(self, tmp_path: Path) -> None:
        self._write_ops_yaml(tmp_path)
        dec_dir = tmp_path / "config" / "agent" / "data_quality" / "decisions"
        dec_dir.mkdir(parents=True, exist_ok=True)
        (dec_dir / "ops_recommendations.yaml").write_text("table: ops_recommendations\nfields: {}\n", encoding="utf-8")
        assert self._run(tmp_path) == ["DQ manifest gate"]

    def test_non_enforced_column_skipped(self, tmp_path: Path) -> None:
        ops_yaml = (
            "tables:\n"
            "  ops_recommendations:\n"
            "    columns:\n"
            "      title:\n"
            "        tests:\n"
            "          - not_null:\n"
            "              enforced: false\n"
        )
        self._write_ops_yaml(tmp_path, ops_yaml)
        assert self._run(tmp_path) == []

    def test_missing_ops_yaml_skips_gracefully(self, tmp_path: Path) -> None:
        assert self._run(tmp_path) == []
