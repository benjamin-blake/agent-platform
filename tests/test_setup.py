#!/usr/bin/env python3
"""Unit tests for setup.py venv activation fix."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

# Load the module under test
_MODULE_PATH = Path(__file__).resolve().parent.parent / "setup.py"
_spec = importlib.util.spec_from_file_location("setup", _MODULE_PATH)
assert _spec and _spec.loader
_setup = importlib.util.module_from_spec(_spec)
sys.modules["setup"] = _setup
_spec.loader.exec_module(_setup)  # type: ignore[union-attr]


class TestFixVenvActivateForGitBash:
    """Tests for the fix_venv_activate_for_git_bash function."""

    def test_converts_windows_backslashes_to_forward_slashes(self, tmp_path: Path) -> None:
        """Verify Windows paths are converted to Git Bash format."""
        # Setup: Create activate script with Windows backslashes
        scripts_dir = tmp_path / ".venv" / "Scripts"
        scripts_dir.mkdir(parents=True)
        activate_file = scripts_dir / "activate"
        activate_file.write_text(
            'VIRTUAL_ENV="C:\\Users\\bblake\\Git Repos\\agent-platform\\.venv"\n'
            "export VIRTUAL_ENV\n"
            'PATH="$VIRTUAL_ENV/Scripts:$PATH"\n',
            encoding="utf-8",
        )

        # Execute
        with patch.object(_setup, "ROOT", tmp_path):
            _setup.fix_venv_activate_for_git_bash()

        # Verify
        result = activate_file.read_text(encoding="utf-8")
        assert 'VIRTUAL_ENV="/c/Users/bblake/Git Repos/agent-platform/.venv"' in result
        assert "C:\\" not in result
        assert "\\\\" not in result

    def test_idempotent_does_not_double_fix(self, tmp_path: Path) -> None:
        """Verify running twice doesn't corrupt already-fixed paths."""
        scripts_dir = tmp_path / ".venv" / "Scripts"
        scripts_dir.mkdir(parents=True)
        activate_file = scripts_dir / "activate"
        already_fixed = 'VIRTUAL_ENV="/c/Users/bblake/Git Repos/agent-platform/.venv"\n'
        activate_file.write_text(already_fixed, encoding="utf-8")

        with patch.object(_setup, "ROOT", tmp_path):
            _setup.fix_venv_activate_for_git_bash()

        result = activate_file.read_text(encoding="utf-8")
        assert result == already_fixed  # Unchanged

    def test_skips_if_activate_not_exists(self, tmp_path: Path) -> None:
        """Verify no error if .venv/Scripts/activate doesn't exist."""
        with patch.object(_setup, "ROOT", tmp_path):
            # Should not raise
            _setup.fix_venv_activate_for_git_bash()

    def test_preserves_other_content(self, tmp_path: Path) -> None:
        """Verify only VIRTUAL_ENV line is modified, rest preserved."""
        scripts_dir = tmp_path / ".venv" / "Scripts"
        scripts_dir.mkdir(parents=True)
        activate_file = scripts_dir / "activate"
        original = (
            "# This is a comment\n"
            'VIRTUAL_ENV="D:\\Projects\\test\\.venv"\n'
            '_OLD_VIRTUAL_PATH="$PATH"\n'
            'PATH="$VIRTUAL_ENV/Scripts:$PATH"\n'
            "export PATH\n"
        )
        activate_file.write_text(original, encoding="utf-8")

        with patch.object(_setup, "ROOT", tmp_path):
            _setup.fix_venv_activate_for_git_bash()

        result = activate_file.read_text(encoding="utf-8")
        assert "# This is a comment\n" in result
        assert 'VIRTUAL_ENV="/d/Projects/test/.venv"' in result
        assert '_OLD_VIRTUAL_PATH="$PATH"\n' in result
        assert 'PATH="$VIRTUAL_ENV/Scripts:$PATH"\n' in result
        assert "export PATH\n" in result

    def test_handles_different_drive_letters(self, tmp_path: Path) -> None:
        """Verify different drive letters are converted correctly."""
        scripts_dir = tmp_path / ".venv" / "Scripts"
        scripts_dir.mkdir(parents=True)
        activate_file = scripts_dir / "activate"
        activate_file.write_text('VIRTUAL_ENV="E:\\dev\\project\\.venv"\n', encoding="utf-8")

        with patch.object(_setup, "ROOT", tmp_path):
            _setup.fix_venv_activate_for_git_bash()

        result = activate_file.read_text(encoding="utf-8")
        assert 'VIRTUAL_ENV="/e/dev/project/.venv"' in result
