"""Tests for validate_structural_size_budget_raises() -- the raise-guard consumer of
scripts.checks._marker_guard (SGE-01/SGE-02/SGE-04, Decision 166).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts.checks.structural.budget_raises import _BUDGET_SPEC, _LONG_LINE_SPEC, validate_structural_size_budget_raises


def _write_current(tmp_path: Path, body: str) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "structural_size_budgets.yaml").write_text(body, encoding="utf-8")


def _write_decisions(tmp_path: Path, decision_numbers: list[int], mentions: dict[int, str] | None = None) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(exist_ok=True)
    mentions = mentions or {}
    parts = []
    for n in decision_numbers:
        header = f"## Decision {n}: Some title (Decided)\n"
        mention = mentions.get(n)
        parts.append(header if not mention else f"{header}\n**Decision:** Authorizes {mention}.\n")
    (docs_dir / "DECISIONS.md").write_text("\n".join(parts), encoding="utf-8")


_BASE_CLASSES_BLOCK = (
    "schema_version: 1\n"
    "classes:\n"
    "  - slug: config\n"
    '    include: ["config/*.yaml"]\n'
    "    governed: true\n"
    "    unit: effective-lines\n"
    "    limit: 500\n"
    "    max_line_chars: 2000\n"
)


class TestTheCriticalSeam:
    """A `classes:` block's `limit`/`max_line_chars` scalars must never leak into either
    section's extraction -- proving the seam, not merely observing it."""

    def test_class_table_scalars_absent_from_both_sections(self, tmp_path: Path) -> None:
        body = _BASE_CLASSES_BLOCK + "budgets:\n  config/heavy.yaml: 800\nlong_line_budgets:\n  config/long.yaml: 2200\n"
        _write_current(tmp_path, body)
        _write_decisions(tmp_path, [])

        text = (tmp_path / "config" / "structural_size_budgets.yaml").read_text(encoding="utf-8")
        budgets = _BUDGET_SPEC.extractor(text)
        long_line = _LONG_LINE_SPEC.extractor(text)

        assert "limit" not in budgets and "limit" not in long_line
        assert "max_line_chars" not in budgets and "max_line_chars" not in long_line

    def test_sections_do_not_cross_leak(self, tmp_path: Path) -> None:
        body = _BASE_CLASSES_BLOCK + "budgets:\n  config/heavy.yaml: 800\nlong_line_budgets:\n  config/long.yaml: 2200\n"
        _write_current(tmp_path, body)
        text = (tmp_path / "config" / "structural_size_budgets.yaml").read_text(encoding="utf-8")
        budgets = _BUDGET_SPEC.extractor(text)
        long_line = _LONG_LINE_SPEC.extractor(text)

        assert "config/heavy.yaml" in budgets and "config/heavy.yaml" not in long_line
        assert "config/long.yaml" in long_line and "config/long.yaml" not in budgets


class TestValidateStructuralSizeBudgetRaises:
    def test_fails_on_unmarked_increase_in_budgets(self, tmp_path: Path) -> None:
        current = _BASE_CLASSES_BLOCK + "budgets:\n  config/heavy.yaml: 800\nlong_line_budgets: {}\n"
        _write_current(tmp_path, current)
        _write_decisions(tmp_path, [])
        base_text = _BASE_CLASSES_BLOCK + "budgets:\n  config/heavy.yaml: 600\nlong_line_budgets: {}\n"
        base_reader = lambda rel: base_text  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_structural_size_budget_raises(failed, base_reader=base_reader)

        assert len(failed) == 1

    def test_fails_on_unmarked_increase_in_long_line_budgets(self, tmp_path: Path) -> None:
        current = _BASE_CLASSES_BLOCK + "budgets: {}\nlong_line_budgets:\n  config/long.yaml: 2500\n"
        _write_current(tmp_path, current)
        _write_decisions(tmp_path, [])
        base_text = _BASE_CLASSES_BLOCK + "budgets: {}\nlong_line_budgets:\n  config/long.yaml: 2100\n"
        base_reader = lambda rel: base_text  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_structural_size_budget_raises(failed, base_reader=base_reader)

        assert len(failed) == 1

    def test_marked_increase_citing_authorizing_decision_passes(self, tmp_path: Path) -> None:
        current = (
            _BASE_CLASSES_BLOCK
            + "budgets:\n  config/heavy.yaml: 800  # raise-approved: dec-166 module growth\nlong_line_budgets: {}\n"
        )
        _write_current(tmp_path, current)
        _write_decisions(tmp_path, [166], mentions={166: "config/heavy.yaml"})
        base_text = _BASE_CLASSES_BLOCK + "budgets:\n  config/heavy.yaml: 600\nlong_line_budgets: {}\n"
        base_reader = lambda rel: base_text  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_structural_size_budget_raises(failed, base_reader=base_reader)

        assert failed == []

    def test_marked_increase_citing_non_authorizing_decision_fails(self, tmp_path: Path) -> None:
        """Authorization, not existence: a marker citing a Decision that exists but never
        mentions the key must still fail."""
        current = (
            _BASE_CLASSES_BLOCK
            + "budgets:\n  config/heavy.yaml: 800  # raise-approved: dec-166 module growth\nlong_line_budgets: {}\n"
        )
        _write_current(tmp_path, current)
        _write_decisions(tmp_path, [166])  # header-only body -- never mentions the key
        base_text = _BASE_CLASSES_BLOCK + "budgets:\n  config/heavy.yaml: 600\nlong_line_budgets: {}\n"
        base_reader = lambda rel: base_text  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_structural_size_budget_raises(failed, base_reader=base_reader)

        assert len(failed) == 1

    def test_retroactive_leg_fails_unchanged_unbacked_marker(self, tmp_path: Path) -> None:
        """The present-markers leg re-scans every marker on every run -- an entry that did
        NOT change in this diff still fails if its marker is unbacked."""
        current = (
            _BASE_CLASSES_BLOCK
            + "budgets:\n  config/heavy.yaml: 800  # raise-approved: dec-166 module growth\nlong_line_budgets: {}\n"
        )
        _write_current(tmp_path, current)
        _write_decisions(tmp_path, [166])  # never mentions the key
        # base == current: nothing changed in this diff.
        base_reader = lambda rel: current  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_structural_size_budget_raises(failed, base_reader=base_reader)

        assert len(failed) == 1

    def test_passes_on_decrease(self, tmp_path: Path) -> None:
        current = _BASE_CLASSES_BLOCK + "budgets:\n  config/heavy.yaml: 600\nlong_line_budgets: {}\n"
        _write_current(tmp_path, current)
        _write_decisions(tmp_path, [])
        base_text = _BASE_CLASSES_BLOCK + "budgets:\n  config/heavy.yaml: 800\nlong_line_budgets: {}\n"
        base_reader = lambda rel: base_text  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_structural_size_budget_raises(failed, base_reader=base_reader)

        assert failed == []

    def test_spec_tokens_and_direction(self) -> None:
        assert _BUDGET_SPEC.token == "raise-approved"
        assert _BUDGET_SPEC.gated_direction == "up"
        assert _LONG_LINE_SPEC.token == "raise-approved"
        assert _LONG_LINE_SPEC.gated_direction == "up"
        assert _BUDGET_SPEC.rel_path == _LONG_LINE_SPEC.rel_path
