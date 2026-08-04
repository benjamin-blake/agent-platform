"""Tests for validate_structural_size_limits() -- the structural-size limit gate
(SGE-01/SGE-02/SGE-04, Decision 166). Every test runs against an INJECTED root (tmp_path),
never the live tree.
"""

from __future__ import annotations

import contextlib
import io
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.checks.structural import _classify
from scripts.checks.structural.size_limits import validate_structural_size_limits

_REGISTRY_TEMPLATE = """\
schema_version: 1
exclusions:
  suffixes: [".py", ".md"]
  dirs: [pip, lambda-packages, docker, .venv, node_modules, .git, personal_scripts]
generated_pinned: []
classes:
  - slug: generated
    include: []
    governed: false
    unit: n/a
    limit: n/a
    max_line_chars: n/a
  - slug: config
    include: ["config/*.yaml", "config/*.yml"]
    governed: true
    unit: effective-lines
    limit: 500
    max_line_chars: 2000
  - slug: workflow_outputs
    include: ["docs/plans/*.yaml"]
    governed: false
    unit: n/a
    limit: n/a
    max_line_chars: n/a
  - slug: residual
    include: []
    governed: true
    unit: effective-lines
    limit: 500
    max_line_chars: 2000
budgets:
{budgets}
long_line_budgets:
{long_line_budgets}
"""


def _write_registry(tmp_path: Path, budgets: str = "", long_line_budgets: str = "") -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    body = _REGISTRY_TEMPLATE.format(budgets=budgets or "  {}", long_line_budgets=long_line_budgets or "  {}")
    (config_dir / "structural_size_budgets.yaml").write_text(body, encoding="utf-8")


def _clear_cache() -> None:
    _classify._registry_cache.clear()


def _mock_ls_files(tracked_paths: list[str]):
    def _run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        result.stdout = "".join(f"{p}\n" for p in tracked_paths)
        return result

    return _run


class TestValidateStructuralSizeLimits:
    def test_over_limit_governed_file_no_roster_entry_fails(self, tmp_path: Path) -> None:
        _write_registry(tmp_path)
        config_dir = tmp_path / "config"
        config_dir.mkdir(exist_ok=True)
        (config_dir / "big.yaml").write_text("key: value\n" * 501, encoding="utf-8")

        _clear_cache()
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.run", _mock_ls_files(["config/big.yaml"])),
        ):
            failed: list[str] = []
            validate_structural_size_limits(failed)

        assert len(failed) == 1

    def test_roster_entry_at_501_passes_at_502_fails(self, tmp_path: Path) -> None:
        """A registered budget of 501 is a ratchet ceiling, not a permanent free pass: a
        501-line file with a 501 roster entry passes; the SAME roster entry (still 501)
        fails again once the file grows to 502 (ratchet direction)."""
        for file_lines, expect_fail in ((501, False), (502, True)):
            _write_registry(tmp_path, budgets="  config/big.yaml: 501")
            config_dir = tmp_path / "config"
            config_dir.mkdir(exist_ok=True)
            (config_dir / "big.yaml").write_text("key: value\n" * file_lines, encoding="utf-8")

            _clear_cache()
            with (
                patch("scripts.checks._common.ROOT", tmp_path),
                patch("scripts.checks._common.run", _mock_ls_files(["config/big.yaml"])),
            ):
                failed: list[str] = []
                validate_structural_size_limits(failed)

            if expect_fail:
                assert len(failed) == 1, f"file_lines={file_lines} expected FAIL"
            else:
                assert failed == [], f"file_lines={file_lines} expected PASS"

    def test_long_line_fails_without_entry_passes_with_entry(self, tmp_path: Path) -> None:
        long_line = "x" * 2001
        for long_line_budgets, expect_fail in ("", True), ("  config/longline.yaml: 2001", False):
            _write_registry(tmp_path, long_line_budgets=long_line_budgets)
            config_dir = tmp_path / "config"
            config_dir.mkdir(exist_ok=True)
            (config_dir / "longline.yaml").write_text(f"key: value\n{long_line}\n", encoding="utf-8")

            _clear_cache()
            with (
                patch("scripts.checks._common.ROOT", tmp_path),
                patch("scripts.checks._common.run", _mock_ls_files(["config/longline.yaml"])),
            ):
                failed: list[str] = []
                validate_structural_size_limits(failed)

            if expect_fail:
                assert len(failed) == 1
            else:
                assert failed == []

    def test_exempt_class_passes_at_5000_lines(self, tmp_path: Path) -> None:
        _write_registry(tmp_path)
        plans_dir = tmp_path / "docs" / "plans"
        plans_dir.mkdir(parents=True)
        (plans_dir / "PLAN-huge.yaml").write_text("key: value\n" * 5000, encoding="utf-8")

        _clear_cache()
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.run", _mock_ls_files(["docs/plans/PLAN-huge.yaml"])),
        ):
            failed: list[str] = []
            validate_structural_size_limits(failed)

        assert failed == []

    def test_unmatched_extension_governed_by_residual_default(self, tmp_path: Path) -> None:
        _write_registry(tmp_path)
        (tmp_path / "surface.hcl2").write_text("x = 1\n" * 501, encoding="utf-8")

        _clear_cache()
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.run", _mock_ls_files(["surface.hcl2"])),
        ):
            failed: list[str] = []
            validate_structural_size_limits(failed)

        assert len(failed) == 1

    def test_failure_message_names_class_and_relief_valves(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir(exist_ok=True)
        registry_text = (
            "schema_version: 1\n"
            'exclusions:\n  suffixes: [".py", ".md"]\n  dirs: []\n'
            "generated_pinned: []\n"
            "classes:\n"
            "  - slug: config\n"
            '    include: ["config/*.yaml"]\n'
            "    governed: true\n"
            "    unit: effective-lines\n"
            "    limit: 500\n"
            "    max_line_chars: 2000\n"
            '    relief_valve: "compact resolved rows"\n'
            "  - slug: residual\n"
            "    include: []\n"
            "    governed: true\n"
            "    unit: effective-lines\n"
            "    limit: 500\n"
            "    max_line_chars: 2000\n"
            "budgets: {}\n"
            "long_line_budgets: {}\n"
        )
        (config_dir / "structural_size_budgets.yaml").write_text(registry_text, encoding="utf-8")
        (config_dir / "big.yaml").write_text("key: value\n" * 501, encoding="utf-8")

        _clear_cache()
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.run", _mock_ls_files(["config/big.yaml"])),
        ):
            failed: list[str] = []
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                validate_structural_size_limits(failed)

        output = buf.getvalue()
        assert "config/big.yaml" in output
        assert "class: config" in output
        assert "compact resolved rows" in output
