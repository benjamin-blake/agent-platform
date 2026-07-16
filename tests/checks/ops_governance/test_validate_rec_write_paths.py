"""Tests for validate_rec_write_paths() -- rec JSONL write-path enforcement."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks.ops_governance.validate_rec_write_paths import validate_rec_write_paths


class TestValidateRecWritePaths:
    """Tests for validate_rec_write_paths() -- rec JSONL write-path enforcement."""

    def test_catches_direct_recs_jsonl_open_append(self, tmp_path: Path, capsys) -> None:
        """Detects RECS_JSONL.open('a') in non-whitelisted scripts."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        bad_file = scripts_dir / "bad_script.py"
        bad_file.write_text(
            'with RECS_JSONL.open("a", encoding="utf-8") as f: f.write("x")\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_rec_write_paths(failed)
        assert len(failed) > 0
        assert any("bad_script.py" in e for e in failed)

    def test_allows_whitelist_portal_file(self, tmp_path: Path, capsys) -> None:
        """ops_data_portal.py is whitelisted and does not trigger the rule."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        portal_file = scripts_dir / "ops_data_portal.py"
        portal_file.write_text(
            'with RECS_JSONL.open("a", encoding="utf-8") as f: f.write("x")\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_rec_write_paths(failed)
        assert failed == []

    def test_allows_whitelist_sync_recommendations(self, tmp_path: Path, capsys) -> None:
        """scripts/sync/recommendations.py is whitelisted and does not trigger the rule."""
        scripts_dir = tmp_path / "scripts"
        sync_dir = scripts_dir / "sync"
        sync_dir.mkdir(parents=True)
        sync_file = sync_dir / "recommendations.py"
        sync_file.write_text(
            'with open(_LOCAL_RECS_FILE, "w", encoding="utf-8") as fh: fh.write("x")\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_rec_write_paths(failed)
        assert failed == []

    def test_clean_scripts_directory_passes(self, tmp_path: Path, capsys) -> None:
        """Scripts with no direct JSONL writes pass without failures."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        clean_file = scripts_dir / "clean_script.py"
        clean_file.write_text(
            "from scripts.ops_data_portal import file_rec\nfile_rec({'title': 'test'})\n",
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_rec_write_paths(failed)
        assert failed == []
