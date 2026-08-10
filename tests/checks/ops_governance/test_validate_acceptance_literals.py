"""Tests for validate_acceptance_literals() -- repo-wide static acceptance-literal lint guard."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks.ops_governance.validate_acceptance_literals import validate_acceptance_literals


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
