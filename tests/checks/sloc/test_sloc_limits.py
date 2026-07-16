"""Tests for validate_sloc_limits() -- Decision 43 SLOC gate."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks.sloc.sloc_limits import _load_sloc_budgets, _update_sloc_budgets, validate_sloc_limits


class TestValidateSlocLimits:
    """Tests for validate_sloc_limits() -- Decision 43 SLOC gate."""

    def test_catches_over_limit_file(self, tmp_path: Path) -> None:
        """Files exceeding 500 SLOC without waiver are flagged."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        big_file = scripts_dir / "big_module.py"
        big_file.write_text("x = 1\n" * 501, encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert len(failed) == 1
        assert "SLOC limits" in failed[0]

    def test_allows_waivered_file(self, tmp_path: Path) -> None:
        """Bare waiver alone is insufficient for >500 SLOC files; budget registration required (Decision 102)."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        big_file = scripts_dir / "waivered.py"
        big_file.write_text(
            "# complexity-waiver: decision-43\n" + "x = 1\n" * 501,
            encoding="utf-8",
        )

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert len(failed) == 1
        assert "SLOC limits" in failed[0]

    def test_allows_under_limit_file(self, tmp_path: Path) -> None:
        """Files under 500 SLOC pass without waiver."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        small_file = scripts_dir / "small.py"
        small_file.write_text("x = 1\n" * 100, encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert failed == []

    def test_skips_init_files(self, tmp_path: Path) -> None:
        """__init__.py files are excluded from SLOC checks."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        init_file = scripts_dir / "__init__.py"
        init_file.write_text("x = 1\n" * 501, encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert failed == []

    def _write_budget(self, tmp_path: Path, entries: dict[str, int]) -> None:
        """Write a sloc_budgets.yaml into tmp_path/config/."""
        config_dir = tmp_path / "config"
        config_dir.mkdir(exist_ok=True)
        lines = ["budgets:"]
        for k, v in entries.items():
            lines.append(f"  {k}: {v}")
        (config_dir / "sloc_budgets.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_registered_file_exceeds_budget_fails(self, tmp_path: Path) -> None:
        """A registered file whose current SLOC exceeds its budget fails the gate."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "heavy.py").write_text("x = 1\n" * 601, encoding="utf-8")
        self._write_budget(tmp_path, {"scripts/heavy.py": 600})

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert len(failed) == 1
        assert "SLOC limits" in failed[0]

    def test_registered_file_at_budget_passes(self, tmp_path: Path) -> None:
        """A registered file at exactly its budget does not fail."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "heavy.py").write_text("x = 1\n" * 600, encoding="utf-8")
        self._write_budget(tmp_path, {"scripts/heavy.py": 600})

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert failed == []

    def test_registered_file_below_budget_passes_advisory(self, tmp_path: Path) -> None:
        """A registered file below its budget passes (advisory only, no failure)."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "heavy.py").write_text("x = 1\n" * 550, encoding="utf-8")
        self._write_budget(tmp_path, {"scripts/heavy.py": 600})

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert failed == []

    def test_oversized_unregistered_with_waiver_fails(self, tmp_path: Path) -> None:
        """A file >500 SLOC with a waiver but no budget registration fails (Decision 102)."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "old_waiver.py").write_text(
            "# complexity-waiver: decision-43\n" + "x = 1\n" * 510,
            encoding="utf-8",
        )
        self._write_budget(tmp_path, {})

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert len(failed) == 1
        assert "SLOC limits" in failed[0]

    def test_stale_waiver_under_limit_is_advisory_not_failure(self, tmp_path: Path) -> None:
        """A file <=500 SLOC with a waiver is a stale-waiver advisory, not a failure."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "small_waiver.py").write_text(
            "# complexity-waiver: decision-43\n" + "x = 1\n" * 100,
            encoding="utf-8",
        )

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert failed == []

    def test_update_sloc_budgets_downward_only(self, tmp_path: Path) -> None:
        """_update_sloc_budgets never raises an existing budget below current SLOC."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (scripts_dir / "growing.py").write_text("x = 1\n" * 600, encoding="utf-8")
        # Seed a budget BELOW current SLOC -- regen must not raise it
        self._write_budget(tmp_path, {"scripts/growing.py": 580})

        with patch("scripts.checks._common.ROOT", tmp_path):
            _update_sloc_budgets()
            result = _load_sloc_budgets()

        assert result["scripts/growing.py"] == 580

    def test_update_sloc_budgets_does_not_seed_new_oversized(self, tmp_path: Path) -> None:
        """_update_sloc_budgets does NOT auto-seed a newly-oversized, unregistered file (B2 /
        Decision 128) -- forces a deliberate raise-approved registration or a decompose instead
        of a frictionless one-command auto-seed. validate_sloc_limits then fails the file until
        it is registered."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (scripts_dir / "new_big.py").write_text("x = 1\n" * 620, encoding="utf-8")
        self._write_budget(tmp_path, {})

        with patch("scripts.checks._common.ROOT", tmp_path):
            _update_sloc_budgets()
            result = _load_sloc_budgets()
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert "scripts/new_big.py" not in result
        assert len(failed) == 1

    def test_update_sloc_budgets_drops_shrunken_file(self, tmp_path: Path) -> None:
        """_update_sloc_budgets drops a file that shrank to <=500 SLOC."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (scripts_dir / "shrunken.py").write_text("x = 1\n" * 100, encoding="utf-8")
        self._write_budget(tmp_path, {"scripts/shrunken.py": 600})

        with patch("scripts.checks._common.ROOT", tmp_path):
            _update_sloc_budgets()
            result = _load_sloc_budgets()

        assert "scripts/shrunken.py" not in result

    def test_update_sloc_budgets_idempotent(self, tmp_path: Path) -> None:
        """rec-2419: running --update-sloc-budgets twice leaves config/sloc_budgets.yaml
        byte-identical the second time (steady-state idempotency)."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (scripts_dir / "steady.py").write_text("x = 1\n" * 550, encoding="utf-8")
        self._write_budget(tmp_path, {"scripts/steady.py": 600})

        with patch("scripts.checks._common.ROOT", tmp_path):
            _update_sloc_budgets()
            first_pass = (tmp_path / "config" / "sloc_budgets.yaml").read_text(encoding="utf-8")
            _update_sloc_budgets()
            second_pass = (tmp_path / "config" / "sloc_budgets.yaml").read_text(encoding="utf-8")

        assert first_pass == second_pass
