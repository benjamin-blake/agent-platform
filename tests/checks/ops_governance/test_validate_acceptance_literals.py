"""Tests for validate_acceptance_literals() -- repo-wide static acceptance-literal lint guard."""

import ast
from pathlib import Path
from unittest.mock import patch

from scripts.checks.ops_governance.validate_acceptance_literals import (
    _find_violations,
    _resolve_string_value,
    _scan_file,
    validate_acceptance_literals,
)


class TestValidateAcceptanceLiterals:
    """Tests for validate_acceptance_literals() -- rec-2772 class-level guard."""

    def test_catches_planted_prose_acceptance_literal(self, tmp_path: Path, capsys) -> None:
        """A prose acceptance value with a stray unbalanced quote fails bash -n; the guard names
        the offending file and line, not just a bare pass/fail."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        bad_file = scripts_dir / "bad_filer.py"
        bad_file.write_text(
            "def _build_rec_fields():\n"
            "    return {\n"
            '        "title": "some sensor rec",\n'
            '        "acceptance": (\n'
            '            "the rec\'s condition clears and it closes automatically."\n'
            "        ),\n"
            "    }\n",
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_acceptance_literals(failed)
        assert len(failed) == 1
        assert "bad_filer.py" in failed[0]
        assert ":5:" in failed[0]

    def test_clean_tree_reports_nothing(self, tmp_path: Path, capsys) -> None:
        """A lint-valid static acceptance produces no violation."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        good_file = scripts_dir / "good_filer.py"
        good_file.write_text(
            "def _build_rec_fields():\n"
            "    return {\n"
            '        "title": "some sensor rec",\n'
            '        "acceptance": "bin/venv-python -m scripts.ci_rca.probe_health --assert-clear",\n'
            "    }\n",
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_acceptance_literals(failed)
        assert failed == []

    def test_dynamic_value_is_skipped_not_guessed(self, tmp_path: Path, capsys) -> None:
        """A non-statically-resolvable acceptance (a variable/call) is skipped, not flagged."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        dynamic_file = scripts_dir / "dynamic_filer.py"
        dynamic_file.write_text(
            "def _build_rec_fields(acceptance_text):\n"
            "    return {\n"
            '        "title": "some sensor rec",\n'
            '        "acceptance": acceptance_text,\n'
            "    }\n",
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_acceptance_literals(failed)
        assert failed == []

    def test_fstring_placeholder_still_catches_syntax_error(self, tmp_path: Path, capsys) -> None:
        """A JoinedStr (f-string) acceptance still gets its literal segments lint-checked, with
        the interpolated {expr} substituted by a placeholder token."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        bad_file = scripts_dir / "bad_fstring_filer.py"
        bad_file.write_text(
            "def _build_rec_fields(fn):\n"
            "    return {\n"
            '        "title": "some sensor rec",\n'
            '        "acceptance": f"the rec\'s {fn} condition clears automatically.",\n'
            "    }\n",
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_acceptance_literals(failed)
        assert len(failed) == 1
        assert "bad_fstring_filer.py" in failed[0]

    def test_non_acceptance_dict_keys_are_ignored(self, tmp_path: Path, capsys) -> None:
        """A field-name map (e.g. cli.py's incidental literals) that happens to have a dict but
        no 'acceptance' key produces no violation -- verified-harmless per plan context."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        unrelated_file = scripts_dir / "unrelated.py"
        unrelated_file.write_text(
            'FIELD_MAP = {"title": "Title", "context": "Context"}\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_acceptance_literals(failed)
        assert failed == []

    def test_resolve_string_value_returns_none_for_non_string_joinedstr_segment(self) -> None:
        """A JoinedStr segment that is neither a str Constant nor a FormattedValue (defensive
        branch -- not reachable via any real f-string, but the resolver must not guess) resolves
        to None."""
        node = ast.JoinedStr(values=[ast.Constant(value=1)])
        assert _resolve_string_value(node) is None

    def test_scan_file_returns_empty_on_os_error(self, tmp_path: Path) -> None:
        """A path that cannot be read (e.g. deleted between glob and read) is skipped, not raised."""
        missing = tmp_path / "does-not-exist.py"
        assert _scan_file(missing) == []

    def test_scan_file_returns_empty_on_syntax_error(self, tmp_path: Path) -> None:
        """A .py file with invalid syntax is skipped, not raised."""
        bad_syntax = tmp_path / "bad_syntax.py"
        bad_syntax.write_text("def broken(:\n", encoding="utf-8")
        assert _scan_file(bad_syntax) == []

    def test_find_violations_includes_personal_scripts_when_present(self, tmp_path: Path) -> None:
        """personal_scripts/ is scanned too, when it exists alongside scripts/."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        personal_dir = tmp_path / "personal_scripts"
        personal_dir.mkdir()
        bad_file = personal_dir / "bad_personal_filer.py"
        bad_file.write_text(
            "def _build_rec_fields():\n"
            "    return {\n"
            '        "acceptance": "the rec\'s condition clears and it closes automatically.",\n'
            "    }\n",
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = _find_violations()
        assert len(violations) == 1
        assert "bad_personal_filer.py" in violations[0]
