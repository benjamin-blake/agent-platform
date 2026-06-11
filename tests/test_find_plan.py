"""Tests for scripts/find_plan.py -- plan file resolution logic."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "find_plan.py"
_spec = importlib.util.spec_from_file_location("find_plan", _SCRIPT_PATH)
_find_plan = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_find_plan)  # type: ignore[union-attr]
sys.modules["find_plan"] = _find_plan

find_plan_file = _find_plan.find_plan_file
ROOT = _find_plan.ROOT


def _mock_git(branch: str, returncode: int = 0) -> MagicMock:
    result = MagicMock()
    result.returncode = returncode
    result.stdout = branch + "\n" if branch else ""
    return result


class TestFindPlanFile:
    def test_agent_branch_returns_branch_specific_plan(self, tmp_path: Path) -> None:
        """Branch agent/foo-bar -> finds PLAN-foo-bar.md."""
        (tmp_path / "docs" / "plans").mkdir(parents=True)
        plan = tmp_path / "docs" / "plans" / "PLAN-foo-bar.md"
        plan.write_text("# Plan", encoding="utf-8")

        with (
            patch("find_plan.subprocess.run", return_value=_mock_git("agent/foo-bar")),
            patch("find_plan.ROOT", tmp_path),
        ):
            result = find_plan_file()

        assert result == plan

    def test_agent_branch_no_branch_plan_falls_back_to_legacy(self, tmp_path: Path) -> None:
        """Branch agent/foo-bar with no PLAN-foo-bar.md -> falls back to PLAN.md."""
        (tmp_path / "docs" / "plans").mkdir(parents=True)
        legacy = tmp_path / "docs" / "plans" / "PLAN.md"
        legacy.write_text("# Legacy", encoding="utf-8")

        with (
            patch("find_plan.subprocess.run", return_value=_mock_git("agent/foo-bar")),
            patch("find_plan.ROOT", tmp_path),
        ):
            result = find_plan_file()

        assert result == legacy

    def test_main_branch_falls_back_to_legacy_plan(self, tmp_path: Path) -> None:
        """Branch main -> no slug extraction, falls back to PLAN.md."""
        (tmp_path / "docs" / "plans").mkdir(parents=True)
        legacy = tmp_path / "docs" / "plans" / "PLAN.md"
        legacy.write_text("# Legacy", encoding="utf-8")

        with (
            patch("find_plan.subprocess.run", return_value=_mock_git("main")),
            patch("find_plan.ROOT", tmp_path),
        ):
            result = find_plan_file()

        assert result == legacy

    def test_no_plan_file_exists_returns_none(self, tmp_path: Path) -> None:
        """Neither branch-specific nor legacy plan -> returns None."""
        with (
            patch("find_plan.subprocess.run", return_value=_mock_git("agent/no-plan")),
            patch("find_plan.ROOT", tmp_path),
        ):
            result = find_plan_file()

        assert result is None

    def test_git_failure_falls_back_to_legacy(self, tmp_path: Path) -> None:
        """Git command fails -> falls back to PLAN.md."""
        (tmp_path / "docs" / "plans").mkdir(parents=True)
        legacy = tmp_path / "docs" / "plans" / "PLAN.md"
        legacy.write_text("# Legacy", encoding="utf-8")

        with (
            patch("find_plan.subprocess.run", return_value=_mock_git("", returncode=1)),
            patch("find_plan.ROOT", tmp_path),
        ):
            result = find_plan_file()

        assert result == legacy

    def test_detached_head_falls_back_to_legacy(self, tmp_path: Path) -> None:
        """Detached HEAD (empty branch string) -> falls back to PLAN.md."""
        (tmp_path / "docs" / "plans").mkdir(parents=True)
        legacy = tmp_path / "docs" / "plans" / "PLAN.md"
        legacy.write_text("# Legacy", encoding="utf-8")

        with (
            patch("find_plan.subprocess.run", return_value=_mock_git("")),
            patch("find_plan.ROOT", tmp_path),
        ):
            result = find_plan_file()

        assert result == legacy

    def test_main_outputs_not_found_when_no_plan(self, tmp_path: Path, capsys) -> None:
        """CLI: prints NOT_FOUND when no plan exists."""
        with (
            patch("find_plan.subprocess.run", return_value=_mock_git("agent/no-plan")),
            patch("find_plan.ROOT", tmp_path),
            patch("find_plan.sys.argv", ["find_plan.py"]),
        ):
            rc = _find_plan.main()

        captured = capsys.readouterr()
        assert rc == 0
        assert captured.out.strip() == "NOT_FOUND"

    def test_main_outputs_path_when_plan_exists(self, tmp_path: Path, capsys) -> None:
        """CLI: prints plan file path when plan exists."""
        (tmp_path / "docs" / "plans").mkdir(parents=True)
        plan = tmp_path / "docs" / "plans" / "PLAN-my-feature.md"
        plan.write_text("# Plan", encoding="utf-8")

        with (
            patch("find_plan.subprocess.run", return_value=_mock_git("agent/my-feature")),
            patch("find_plan.ROOT", tmp_path),
            patch("find_plan.sys.argv", ["find_plan.py"]),
        ):
            rc = _find_plan.main()

        captured = capsys.readouterr()
        assert rc == 0
        assert str(plan) in captured.out.strip()


class TestFindPlanFileExplicit:
    def test_explicit_path_exists_returns_path(self, tmp_path: Path) -> None:
        """Explicit path that exists -> returns that Path."""
        (tmp_path / "docs" / "plans").mkdir(parents=True)
        plan = tmp_path / "docs" / "plans" / "PLAN-web-workflow.md"
        plan.write_text("# Plan", encoding="utf-8")

        with patch("find_plan.ROOT", tmp_path):
            result = find_plan_file(explicit=str(plan))

        assert result == plan

    def test_explicit_path_relative_resolves_under_root(self, tmp_path: Path) -> None:
        """Explicit relative path is resolved against ROOT."""
        (tmp_path / "docs" / "plans").mkdir(parents=True)
        plan = tmp_path / "docs" / "plans" / "PLAN-rel.md"
        plan.write_text("# Plan", encoding="utf-8")

        with patch("find_plan.ROOT", tmp_path):
            result = find_plan_file(explicit="docs/plans/PLAN-rel.md")

        assert result == plan

    def test_explicit_path_missing_returns_none(self, tmp_path: Path) -> None:
        """Explicit path that does not exist -> returns None (no fallback)."""
        (tmp_path / "docs" / "plans").mkdir(parents=True)
        legacy = tmp_path / "docs" / "plans" / "PLAN.md"
        legacy.write_text("# Legacy", encoding="utf-8")

        with patch("find_plan.ROOT", tmp_path):
            result = find_plan_file(explicit="docs/plans/PLAN-does-not-exist.md")

        assert result is None

    def test_explicit_missing_does_not_fall_back_to_legacy(self, tmp_path: Path) -> None:
        """Explicit-but-missing path must NOT fall back to PLAN.md."""
        (tmp_path / "docs" / "plans").mkdir(parents=True)
        legacy = tmp_path / "docs" / "plans" / "PLAN.md"
        legacy.write_text("# Legacy", encoding="utf-8")

        with patch("find_plan.ROOT", tmp_path):
            result = find_plan_file(explicit="docs/plans/PLAN-no-such-file.md")

        assert result is None
        assert result != legacy

    def test_main_explicit_path_exists_prints_path(self, tmp_path: Path, capsys) -> None:
        """CLI: explicit arg with existing file prints the path."""
        (tmp_path / "docs" / "plans").mkdir(parents=True)
        plan = tmp_path / "docs" / "plans" / "PLAN-explicit.md"
        plan.write_text("# Plan", encoding="utf-8")

        with (
            patch("find_plan.ROOT", tmp_path),
            patch("find_plan.sys.argv", ["find_plan.py", str(plan)]),
        ):
            rc = _find_plan.main()

        captured = capsys.readouterr()
        assert rc == 0
        assert str(plan) in captured.out.strip()

    def test_main_explicit_path_missing_prints_not_found(self, tmp_path: Path, capsys) -> None:
        """CLI: explicit arg with missing file prints NOT_FOUND."""
        with (
            patch("find_plan.ROOT", tmp_path),
            patch("find_plan.sys.argv", ["find_plan.py", "docs/plans/PLAN-ghost.md"]),
        ):
            rc = _find_plan.main()

        captured = capsys.readouterr()
        assert rc == 0
        assert captured.out.strip() == "NOT_FOUND"


class TestYamlFirstResolution:
    def test_yaml_preferred_over_md_for_branch(self, tmp_path: Path) -> None:
        """Branch resolution returns PLAN-{slug}.yaml when both .yaml and .md exist."""
        (tmp_path / "docs" / "plans").mkdir(parents=True)
        plan_yaml = tmp_path / "docs" / "plans" / "PLAN-foo-bar.yaml"
        plan_yaml.write_text("slug: foo-bar", encoding="utf-8")
        plan_md = tmp_path / "docs" / "plans" / "PLAN-foo-bar.md"
        plan_md.write_text("# Plan", encoding="utf-8")

        with (
            patch("find_plan.subprocess.run", return_value=_mock_git("agent/foo-bar")),
            patch("find_plan.ROOT", tmp_path),
        ):
            result = find_plan_file()

        assert result == plan_yaml

    def test_md_branch_fallback_emits_deprecation_warning(self, tmp_path: Path, caplog) -> None:
        """Resolving PLAN-{slug}.md (no .yaml) warns that the .md path is deprecated."""
        (tmp_path / "docs" / "plans").mkdir(parents=True)
        plan_md = tmp_path / "docs" / "plans" / "PLAN-foo-bar.md"
        plan_md.write_text("# Plan", encoding="utf-8")

        with (
            patch("find_plan.subprocess.run", return_value=_mock_git("agent/foo-bar")),
            patch("find_plan.ROOT", tmp_path),
            caplog.at_level("WARNING", logger="find_plan"),
        ):
            result = find_plan_file()

        assert result == plan_md
        assert any("deprecated" in r.message for r in caplog.records)

    def test_yaml_resolution_emits_no_warning(self, tmp_path: Path, caplog) -> None:
        """Resolving PLAN-{slug}.yaml emits no deprecation warning."""
        (tmp_path / "docs" / "plans").mkdir(parents=True)
        plan_yaml = tmp_path / "docs" / "plans" / "PLAN-foo-bar.yaml"
        plan_yaml.write_text("slug: foo-bar", encoding="utf-8")

        with (
            patch("find_plan.subprocess.run", return_value=_mock_git("agent/foo-bar")),
            patch("find_plan.ROOT", tmp_path),
            caplog.at_level("WARNING", logger="find_plan"),
        ):
            result = find_plan_file()

        assert result == plan_yaml
        assert not caplog.records

    def test_explicit_md_path_emits_deprecation_warning(self, tmp_path: Path, caplog) -> None:
        """An explicit .md path still resolves but warns."""
        (tmp_path / "docs" / "plans").mkdir(parents=True)
        plan_md = tmp_path / "docs" / "plans" / "PLAN-explicit.md"
        plan_md.write_text("# Plan", encoding="utf-8")

        with (
            patch("find_plan.ROOT", tmp_path),
            caplog.at_level("WARNING", logger="find_plan"),
        ):
            result = find_plan_file(explicit=str(plan_md))

        assert result == plan_md
        assert any("deprecated" in r.message for r in caplog.records)

    def test_legacy_plan_md_fallback_warns(self, tmp_path: Path, caplog) -> None:
        """Legacy PLAN.md fallback also emits the deprecation warning."""
        (tmp_path / "docs" / "plans").mkdir(parents=True)
        legacy = tmp_path / "docs" / "plans" / "PLAN.md"
        legacy.write_text("# Legacy", encoding="utf-8")

        with (
            patch("find_plan.subprocess.run", return_value=_mock_git("main")),
            patch("find_plan.ROOT", tmp_path),
            caplog.at_level("WARNING", logger="find_plan"),
        ):
            result = find_plan_file()

        assert result == legacy
        assert any("deprecated" in r.message for r in caplog.records)
