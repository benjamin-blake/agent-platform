"""Tests for validate_ducklake_version_lockstep() -- the OQ.12 SSOT drift gate."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks.misc.validate_ducklake_version_lockstep import validate_ducklake_version_lockstep


class TestDucklakeVersionLockstepGate:
    """Tests for validate_ducklake_version_lockstep() -- the OQ.12 SSOT drift gate."""

    def test_passes_on_coherent_tree(self, tmp_path: Path) -> None:
        """Gate passes when requirements.txt is in sync and no literal in derive surfaces."""
        import scripts.sync.ducklake_version as _sdv_inner  # noqa: PLC0415

        # coherent requirements.txt
        req = tmp_path / "requirements.txt"
        req.write_text(_sdv_inner._expected_floor_line("1.5.4") + "\n", encoding="utf-8")

        src = tmp_path / "src" / "common"
        src.mkdir(parents=True)
        runtime = src / "ducklake_runtime.py"
        no_literal = (
            "# no literal\n"
            "from src.common.ducklake_version import pinned_duckdb_version as _p\n"
            "_PINNED_DUCKDB_VERSION = None\n"
        )
        runtime.write_text(no_literal, encoding="utf-8")

        scripts = tmp_path / "scripts"
        scripts.mkdir()
        build = scripts / "build_lambda.py"
        build.write_text(
            "from src.common.ducklake_version import pinned_duckdb_version as _p\nPINNED_DUCKDB_VERSION = _p()\n",
            encoding="utf-8",
        )

        import scripts.sync.ducklake_version as sdv  # noqa: PLC0415

        failed: list[str] = []
        with patch.object(sdv, "_get_pinned_version", return_value="1.5.4"):
            with patch("scripts.checks._common.ROOT", tmp_path):
                validate_ducklake_version_lockstep(failed)
        assert failed == [], failed

    def test_fails_when_requirements_drifts(self, tmp_path: Path) -> None:
        """Gate fails when requirements.txt has old floor."""
        req = tmp_path / "requirements.txt"
        req.write_text("duckdb>=1.5.3  # old\n", encoding="utf-8")

        src = tmp_path / "src" / "common"
        src.mkdir(parents=True)
        (src / "ducklake_runtime.py").write_text("# no literal\n", encoding="utf-8")

        scripts = tmp_path / "scripts"
        scripts.mkdir()
        (scripts / "build_lambda.py").write_text("# no literal\n", encoding="utf-8")

        import scripts.sync.ducklake_version as sdv  # noqa: PLC0415

        failed: list[str] = []
        with patch.object(sdv, "_get_pinned_version", return_value="1.5.4"):
            with patch("scripts.checks._common.ROOT", tmp_path):
                validate_ducklake_version_lockstep(failed)
        assert any("duckdb floor" in f or "requirements" in f for f in failed), failed

    def test_fails_when_literal_in_derive_surface(self, tmp_path: Path) -> None:
        """Gate fails when a raw PINNED_DUCKDB_VERSION = '...' literal is in a derive surface."""
        import scripts.sync.ducklake_version as _sdv_inner  # noqa: PLC0415

        req = tmp_path / "requirements.txt"
        req.write_text(_sdv_inner._expected_floor_line("1.5.4") + "\n", encoding="utf-8")

        src = tmp_path / "src" / "common"
        src.mkdir(parents=True)
        # reintroduce a hardcoded literal
        (src / "ducklake_runtime.py").write_text('PINNED_DUCKDB_VERSION = "1.5.3"\n', encoding="utf-8")

        scripts = tmp_path / "scripts"
        scripts.mkdir()
        (scripts / "build_lambda.py").write_text("# no literal\n", encoding="utf-8")

        import scripts.sync.ducklake_version as sdv  # noqa: PLC0415

        failed: list[str] = []
        with patch.object(sdv, "_get_pinned_version", return_value="1.5.4"):
            with patch("scripts.checks._common.ROOT", tmp_path):
                validate_ducklake_version_lockstep(failed)
        assert any("hardcoded" in f or "literal" in f or "ducklake_runtime" in f for f in failed), failed
