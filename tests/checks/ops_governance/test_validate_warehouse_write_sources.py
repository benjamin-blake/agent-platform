"""Tests for validate_warehouse_write_sources() -- warehouse-as-source invariant."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks.ops_governance.validate_warehouse_write_sources import validate_warehouse_write_sources


class TestValidateWarehouseWriteSources:
    """Tests for validate_warehouse_write_sources() -- warehouse-as-source invariant."""

    def test_catches_unwhitelisted_ops_recommendations_write(self, tmp_path: Path, capsys) -> None:
        """Detects OpsWriter().write('ops_*', ...) in non-whitelisted scripts."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        bad_file = scripts_dir / "bad_replay.py"
        bad_file.write_text(
            'OpsWriter().write("ops_recommendations", entry)\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_warehouse_write_sources(failed)
        assert len(failed) > 0
        assert any("bad_replay.py" in e for e in failed)

    def test_catches_aliased_writer_call(self, tmp_path: Path, capsys) -> None:
        """Detects writer.write('ops_*', ...) where writer is an OpsWriter instance."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        bad_file = scripts_dir / "bad_alias.py"
        bad_file.write_text(
            'writer = OpsWriter()\nwriter.write("ops_decisions", entry)\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_warehouse_write_sources(failed)
        assert len(failed) > 0
        assert any("bad_alias.py" in e for e in failed)

    def test_allows_whitelisted_portal_for_unmigrated_tables(self, tmp_path: Path, capsys) -> None:
        """ops_data_portal.py stays whitelisted for the NOT-yet-migrated tables (session_log)."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        portal_file = scripts_dir / "ops_data_portal.py"
        portal_file.write_text(
            'OpsWriter().write("ops_session_log", merged)\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_warehouse_write_sources(failed)
        assert failed == []

    def test_migrated_tables_opswriter_blocked_even_for_whitelisted_portal(self, tmp_path: Path, capsys) -> None:
        """Decision 84 I-1: the migrated-tables block applies to ALL files including the whitelist.

        Even whitelisted callers (ops_data_portal.py) must not route ops_recommendations,
        ops_decisions, or ops_priority_queue through OpsWriter -- readers serve DuckLake, so an
        Iceberg write is a silent split-brain. The guard must fire regardless of whitelist status.
        """
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        portal_file = scripts_dir / "ops_data_portal.py"
        for table in ("ops_recommendations", "ops_decisions", "ops_priority_queue"):
            portal_file.write_text(
                f'OpsWriter().write("{table}", merged)\n',
                encoding="utf-8",
            )
            with patch("scripts.checks._common.ROOT", tmp_path):
                failed: list[str] = []
                validate_warehouse_write_sources(failed)
            assert len(failed) > 0, f"migrated-table block must fire for {table}"
            assert any("DuckLake-migrated table" in e for e in failed)

    def test_s3_log_store_queue_producer_exemption(self, tmp_path: Path, capsys) -> None:
        """The dormant queue producer keeps its tracked exemption until the T2.26 repoint."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        store_file = scripts_dir / "s3_log_store.py"
        store_file.write_text(
            'ops.write("ops_priority_queue", enriched)\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_warehouse_write_sources(failed)
        assert not any("DuckLake-migrated table" in e for e in failed)

    def test_clean_script_with_no_warehouse_writes_passes(self, tmp_path: Path, capsys) -> None:
        """Scripts that only call portal functions (file_rec) pass cleanly."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        clean_file = scripts_dir / "clean_script.py"
        clean_file.write_text(
            "from scripts.ops_data_portal import file_rec\nfile_rec({'title': 'test'})\n",
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_warehouse_write_sources(failed)
        assert failed == []
