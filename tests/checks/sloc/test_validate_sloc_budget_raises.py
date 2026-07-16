"""Tests for validate_sloc_budget_raises() -- Decision 128 SLOC budget-raise guardrail."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks.sloc.validate_sloc_budget_raises import validate_sloc_budget_raises


class TestValidateSlocBudgetRaises:
    """Tests for validate_sloc_budget_raises() -- Decision 128 SLOC budget-raise guardrail."""

    def _write_current(self, tmp_path: Path, body: str) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir(exist_ok=True)
        (config_dir / "sloc_budgets.yaml").write_text(body, encoding="utf-8")

    def _write_decisions(self, tmp_path: Path, decision_numbers: list[int]) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir(exist_ok=True)
        text = "\n".join(f"## Decision {n}: Some title (Decided)\n" for n in decision_numbers)
        (docs_dir / "DECISIONS.md").write_text(text, encoding="utf-8")

    def test_fails_on_unmarked_increase(self, tmp_path: Path) -> None:
        self._write_current(tmp_path, "budgets:\n  scripts/heavy.py: 800\n")
        self._write_decisions(tmp_path, [])
        base_reader = lambda rel: "budgets:\n  scripts/heavy.py: 600\n"  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_budget_raises(failed, base_reader=base_reader)

        assert len(failed) == 1
        assert "SLOC budget-raise" in failed[0]

    def test_passes_with_valid_marker_and_valid_decision(self, tmp_path: Path) -> None:
        self._write_current(tmp_path, "budgets:\n  scripts/heavy.py: 800  # raise-approved: dec-102 module cohesion\n")
        self._write_decisions(tmp_path, [102])
        base_reader = lambda rel: "budgets:\n  scripts/heavy.py: 600\n"  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_budget_raises(failed, base_reader=base_reader)

        assert failed == []

    def test_fails_when_marker_cites_nonexistent_decision(self, tmp_path: Path) -> None:
        self._write_current(tmp_path, "budgets:\n  scripts/heavy.py: 800  # raise-approved: dec-999 bogus\n")
        self._write_decisions(tmp_path, [102])
        base_reader = lambda rel: "budgets:\n  scripts/heavy.py: 600\n"  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_budget_raises(failed, base_reader=base_reader)

        assert len(failed) == 1

    def test_fails_new_registration_without_marker(self, tmp_path: Path) -> None:
        self._write_current(tmp_path, "budgets:\n  scripts/new_big.py: 550\n")
        self._write_decisions(tmp_path, [])
        base_reader = lambda rel: "budgets: {}\n"  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_budget_raises(failed, base_reader=base_reader)

        assert len(failed) == 1

    def test_passes_new_registration_with_valid_marker(self, tmp_path: Path) -> None:
        self._write_current(tmp_path, "budgets:\n  scripts/new_big.py: 550  # raise-approved: dec-102 new module\n")
        self._write_decisions(tmp_path, [102])
        base_reader = lambda rel: "budgets: {}\n"  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_budget_raises(failed, base_reader=base_reader)

        assert failed == []

    def test_passes_on_decrease(self, tmp_path: Path) -> None:
        self._write_current(tmp_path, "budgets:\n  scripts/heavy.py: 600\n")
        self._write_decisions(tmp_path, [])
        base_reader = lambda rel: "budgets:\n  scripts/heavy.py: 800\n"  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_budget_raises(failed, base_reader=base_reader)

        assert failed == []

    def test_passes_on_removal(self, tmp_path: Path) -> None:
        self._write_current(tmp_path, "budgets: {}\n")
        self._write_decisions(tmp_path, [])
        base_reader = lambda rel: "budgets:\n  scripts/heavy.py: 800\n"  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_budget_raises(failed, base_reader=base_reader)

        assert failed == []

    def test_skips_when_base_unreachable(self, tmp_path: Path) -> None:
        self._write_current(tmp_path, "budgets:\n  scripts/heavy.py: 800\n")
        self._write_decisions(tmp_path, [])
        base_reader = lambda rel: None  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_budget_raises(failed, base_reader=base_reader)

        assert failed == []

    def test_no_current_budgets_file_is_a_noop(self, tmp_path: Path) -> None:
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_budget_raises(failed, base_reader=lambda rel: "budgets: {}\n")

        assert failed == []
