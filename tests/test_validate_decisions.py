"""Tests for validate_decisions_local_writes() in scripts/validate.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

_SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "validate.py"

if "validate" in sys.modules:
    _validate = sys.modules["validate"]
else:
    _spec = importlib.util.spec_from_file_location("validate", _SCRIPT_PATH)
    _validate = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
    _spec.loader.exec_module(_validate)  # type: ignore[union-attr]
    sys.modules["validate"] = _validate

validate_decisions_local_writes = _validate.validate_decisions_local_writes


class TestValidateDecisionsLocalWrites:
    """Tests for validate_decisions_local_writes() (D10)."""

    def test_catches_decisions_jsonl_open_write(self, tmp_path: Path, capsys) -> None:
        """Detects DECISIONS_JSONL.open('w') in a non-whitelisted script."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "bad_script.py").write_text(
            'with DECISIONS_JSONL.open("w", encoding="utf-8") as f: f.write("x")\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_decisions_local_writes(failed)
        assert len(failed) > 0
        assert any("bad_script.py" in e for e in failed)

    def test_catches_decisions_jsonl_open_append(self, tmp_path: Path, capsys) -> None:
        """Detects DECISIONS_JSONL.open('a') in a non-whitelisted script."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "replay_script.py").write_text(
            'with DECISIONS_JSONL.open("a", encoding="utf-8") as f: f.write("x")\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_decisions_local_writes(failed)
        assert len(failed) > 0

    def test_allows_whitelist_ops_data_portal(self, tmp_path: Path, capsys) -> None:
        """ops_data_portal.py is whitelisted and does not trigger the rule."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "ops_data_portal.py").write_text(
            'with DECISIONS_JSONL.open("a", encoding="utf-8") as f: f.write("x")\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_decisions_local_writes(failed)
        assert failed == []

    def test_allows_whitelist_sync_ops(self, tmp_path: Path, capsys) -> None:
        """sync_ops.py is whitelisted and does not trigger the rule."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "sync_ops.py").write_text(
            'with DECISIONS_JSONL.open("a", encoding="utf-8") as f: f.write("x")\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_decisions_local_writes(failed)
        assert failed == []

    def test_clean_scripts_directory_passes(self, tmp_path: Path, capsys) -> None:
        """Scripts that only read the decisions cache pass without failures."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "clean_reader.py").write_text(
            "from scripts.ops_data_portal import file_decision\nfile_decision({'title': 'test'})\n",
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_decisions_local_writes(failed)
        assert failed == []
