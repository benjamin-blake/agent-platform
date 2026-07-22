"""Tests for validate_prose_budget_raises() -- Decision 128 marker mechanism applied to
config/prose_budgets.yaml (self-contained mirror of
tests/checks/sloc/test_validate_sloc_budget_raises.py)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.checks.prose.prose_budget_raises import _default_base_reader, validate_prose_budget_raises


class TestValidateProseBudgetRaises:
    """Tests for validate_prose_budget_raises() -- Decision 128 marker mechanism."""

    def _write_current(self, tmp_path: Path, body: str) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir(exist_ok=True)
        (config_dir / "prose_budgets.yaml").write_text(body, encoding="utf-8")

    def _write_decisions(self, tmp_path: Path, decision_numbers: list[int]) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir(exist_ok=True)
        text = "\n".join(f"## Decision {n}: Some title (Decided)\n" for n in decision_numbers)
        (docs_dir / "DECISIONS.md").write_text(text, encoding="utf-8")

    def test_fails_on_unmarked_increase(self, tmp_path: Path) -> None:
        self._write_current(tmp_path, "S1:\n  root_ambient_load_set: 40000\n")
        self._write_decisions(tmp_path, [])
        base_reader = lambda rel: "S1:\n  root_ambient_load_set: 30000\n"  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_prose_budget_raises(failed, base_reader=base_reader)

        assert len(failed) == 1
        assert "Prose budget-raise" in failed[0]

    def test_passes_with_valid_marker_and_valid_decision(self, tmp_path: Path) -> None:
        self._write_current(
            tmp_path,
            "S1:\n  root_ambient_load_set: 40000  # raise-approved: dec-134 consumer-sized ceiling\n",
        )
        self._write_decisions(tmp_path, [134])
        base_reader = lambda rel: "S1:\n  root_ambient_load_set: 30000\n"  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_prose_budget_raises(failed, base_reader=base_reader)

        assert failed == []

    def test_fails_when_marker_cites_nonexistent_decision(self, tmp_path: Path) -> None:
        self._write_current(tmp_path, "S1:\n  root_ambient_load_set: 40000  # raise-approved: dec-999 bogus\n")
        self._write_decisions(tmp_path, [134])
        base_reader = lambda rel: "S1:\n  root_ambient_load_set: 30000\n"  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_prose_budget_raises(failed, base_reader=base_reader)

        assert len(failed) == 1

    def test_non_marker_comment_is_treated_as_no_marker(self, tmp_path: Path) -> None:
        self._write_current(tmp_path, "S1:\n  root_ambient_load_set: 40000  # just a note, not a marker\n")
        self._write_decisions(tmp_path, [])
        base_reader = lambda rel: "S1:\n  root_ambient_load_set: 30000\n"  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_prose_budget_raises(failed, base_reader=base_reader)

        assert len(failed) == 1

    def test_fails_new_registration_without_marker(self, tmp_path: Path) -> None:
        self._write_current(tmp_path, "S2:\n  docs/CLAUDE.md: 4000\n")
        self._write_decisions(tmp_path, [])
        base_reader = lambda rel: "S2:\n  x: 1\n"  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_prose_budget_raises(failed, base_reader=base_reader)

        assert len(failed) == 1

    def test_passes_new_registration_with_valid_marker(self, tmp_path: Path) -> None:
        self._write_current(tmp_path, "S2:\n  docs/CLAUDE.md: 4000  # raise-approved: dec-127 new CLAUDE.md\n")
        self._write_decisions(tmp_path, [127])
        base_reader = lambda rel: "S2:\n  x: 1\n"  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_prose_budget_raises(failed, base_reader=base_reader)

        assert failed == []

    def test_passes_on_decrease(self, tmp_path: Path) -> None:
        self._write_current(tmp_path, "S1:\n  root_ambient_load_set: 30000\n")
        self._write_decisions(tmp_path, [])
        base_reader = lambda rel: "S1:\n  root_ambient_load_set: 40000\n"  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_prose_budget_raises(failed, base_reader=base_reader)

        assert failed == []

    def test_passes_on_removal(self, tmp_path: Path) -> None:
        self._write_current(tmp_path, "S1: {}\n")
        self._write_decisions(tmp_path, [])
        base_reader = lambda rel: "S1:\n  root_ambient_load_set: 40000\n"  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_prose_budget_raises(failed, base_reader=base_reader)

        assert failed == []

    def test_skips_when_base_unreachable(self, tmp_path: Path) -> None:
        self._write_current(tmp_path, "S1:\n  root_ambient_load_set: 40000\n")
        self._write_decisions(tmp_path, [])
        base_reader = lambda rel: None  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_prose_budget_raises(failed, base_reader=base_reader)

        assert failed == []

    def test_no_current_budgets_file_is_a_noop(self, tmp_path: Path) -> None:
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_prose_budget_raises(failed, base_reader=lambda rel: "S1:\n  root_ambient_load_set: 1\n")

        assert failed == []

    def test_blank_and_comment_only_lines_are_skipped(self, tmp_path: Path) -> None:
        self._write_current(
            tmp_path,
            "# header comment\n\nS1:\n  root_ambient_load_set: 40000\n\n# trailing comment\n",
        )
        self._write_decisions(tmp_path, [])
        base_reader = lambda rel: "S1:\n  root_ambient_load_set: 40000\n"  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_prose_budget_raises(failed, base_reader=base_reader)

        assert failed == []

    def test_relief_valve_message_never_names_split_or_decompose(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._write_current(tmp_path, "S1:\n  root_ambient_load_set: 40000\n")
        self._write_decisions(tmp_path, [])
        base_reader = lambda rel: "S1:\n  root_ambient_load_set: 30000\n"  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_prose_budget_raises(failed, base_reader=base_reader)

        out = capsys.readouterr().out.lower()
        assert len(failed) == 1
        assert "relocate" in out
        assert "defer" in out
        assert "raise" in out
        assert "split" not in out
        assert "decompose" not in out

    def test_default_base_reader_returns_none_on_nonzero_exit(self) -> None:
        fake_result = type("FakeResult", (), {"returncode": 1, "stdout": ""})()
        with patch("scripts.checks._common.run", return_value=fake_result):
            assert _default_base_reader("config/prose_budgets.yaml") is None

    def test_default_base_reader_returns_stdout_on_success(self) -> None:
        fake_result = type("FakeResult", (), {"returncode": 0, "stdout": "S1:\n  root_ambient_load_set: 1\n"})()
        with patch("scripts.checks._common.run", return_value=fake_result):
            assert _default_base_reader("config/prose_budgets.yaml") == "S1:\n  root_ambient_load_set: 1\n"
